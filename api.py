from flask import Flask, request, jsonify, abort, Blueprint, send_from_directory
from dotenv import load_dotenv
import os
import subprocess
import threading
import re
import sqlite3
import uuid
import logging
from queue import Queue
from functools import wraps
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from base64 import b64decode
import time

load_dotenv()


def find_position_in_queue(q, task_id):
    """
    查找队列中元素的位置
    :param q: 队列对象
    :param task_id: 要查找的元素id
    :return: 元素在队列中的位置，如果没有找到则返回-1
    """
    # fixme: 没加锁，因为自带的queue不方便查找只能遍历 ，量大了会严重阻塞
    # with q.mutex:  # 使用队列的锁来确保线程安全
    # 将队列转换为列表
    queue_list = list(q.queue)
    # 遍历list，按照其中tuple的task id，尝试找到元素的位置
    for task_tuple in queue_list:
        if len(task_tuple) > 0 and task_tuple[0] == task_id:
            return queue_list.index(task_tuple)
    return -1


class Config:
    _tokenValidPeriod = os.environ.get("TOKEN_VALID_MINUTE", "1")

    tokenExpire = os.environ.get("TOKEN_EXPIRE", "")
    tokenThreshold = int(float(_tokenValidPeriod) * 60)
    pythonPath = os.environ.get("PYTHON_PATH", "/root/miniconda3/envs/sadtalker/bin/python")
    logLevel = os.environ.get("LOG_LEVEL", "DEBUG")
    uploadDir = os.environ.get("UPLOAD_DIR", 'uploads/')
    resultDir = os.environ.get("RESULT_DIR", 'results/')
    apiPort = os.environ.get("API_PORT", "5000")
    prod = os.environ.get("FLASK_DEBUG", "false")
    stArg = os.environ.get("ST_ARG", "")


TASK_STATUS_PENDING = "pending"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_SUCCESS = "success"
TASK_STATUS_MISSING = "missing_result"
TASK_STATUS_FAILED = "failed"

DB = 'tasks.db'

config = Config()

ALLOWED_EXTENSIONS = {'mov', 'png', 'jpg', 'jpeg', 'gif', 'mp3', 'wav', 'm4a', 'mp4', 'heic'}
root = Blueprint('sadTalker', __name__, url_prefix="/sadTalker")
app = Flask(__name__)

# 创建一个队列
task_queue = Queue()
# 创建数据库和表（如果不存在的话）
conn = sqlite3.connect(DB, check_same_thread=False)
with conn:
    conn.execute('''CREATE TABLE IF NOT EXISTS tasks
             (id TEXT PRIMARY KEY, result TEXT, status TEXT)''')

# 配置日志
logging.basicConfig(level=config.logLevel, format='[%(filename)s:%(lineno)d] %(asctime)s %(levelname)s:%(message)s')
logger = logging.getLogger(__name__)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def process_st_args(arg_string):
    return arg_string.split(" ")


def authenticate(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        openid = request.form.get('openid')
        ticket = request.form.get('ticket')

        logger.debug(f"Authenticating with openid: {openid}, ticket: {ticket}")

        if not openid or not ticket:
            logger.debug("Authentication required")
            return jsonify(error="Authentication required"), 401

        try:
            # 读取私钥
            with open('certs/private.pem', 'r') as priv_file:
                private_key = RSA.import_key(priv_file.read())

            # 解密ticket
            cipher = PKCS1_v1_5.new(private_key)
            decoded_ticket = b64decode(ticket)
            decrypted_ticket = cipher.decrypt(decoded_ticket, None).decode('utf-8')
            logger.debug(f"Decrypted ticket: {decrypted_ticket}")
            # 验证格式和时间戳
            if not decrypted_ticket.startswith(openid):
                return jsonify(error="Invalid authentication"), 401
            ticket_timestamp = int(decrypted_ticket.lstrip(openid))
            if config.tokenExpire and (time.time() - ticket_timestamp > config.tokenThreshold):
                logger.debug(f"Authentication expired for openid: {openid}")
                return jsonify(error="Authentication expired"), 401

        except Exception as e:
            logger.debug(f"Authentication failed for openid: {e}")
            return jsonify(error="Authentication failed"), 401

        return f(*args, **kwargs)

    return decorated_function


@root.route('/upload', methods=['POST'])
@authenticate
def upload_file():
    if 'photo' not in request.files or 'audio' not in request.files:
        return jsonify(error="No photo/audio part in the request"), 400
    photo = request.files['photo']
    audio = request.files['audio']
    if photo.filename == '' or audio.filename == '':
        return jsonify(error="No selected file"), 400
    if photo and allowed_file(photo.filename) and audio and allowed_file(audio.filename):
        task_id = str(uuid.uuid4())  # 生成唯一ID
        photo_filename = os.path.join(config.uploadDir, photo.filename)
        audio_filename = os.path.join(config.uploadDir, audio.filename)
        photo.save(photo_filename)
        audio.save(audio_filename)
        # 将任务添加到队列
        task_queue.put((task_id, photo_filename, audio_filename))
        with conn as c:
            c.execute('INSERT INTO tasks (id, result, status) VALUES (?,?,?)', (task_id, None, TASK_STATUS_PENDING))
        logger.info(f"任务 {task_id} 的状态更新为 {TASK_STATUS_PENDING}")
        return jsonify(task_id=task_id), 202
    else:
        return jsonify(error="File type not allowed"), 400


@root.route('/status', methods=['POST'])
@authenticate
def get_status():
    task_id = request.form.get("task_id")
    with conn:
        c = conn.cursor()
        c.execute('SELECT result, status FROM tasks WHERE id=?', (task_id,))
        task = c.fetchone()
    if task:
        return jsonify(id=task_id, result=task[0], status=task[1], index=find_position_in_queue(task_queue, task_id))
    else:
        abort(404)


@root.route('/download', methods=['POST'])
@authenticate
def download_result():
    """
    下载结果文件。
    """
    filename = request.form.get('filename')
    if not filename:
        return jsonify(error="Filename not provided"), 400
    try:
        return send_from_directory(config.resultDir, filename, as_attachment=True)
    except FileNotFoundError:
        abort(404)


def update_task_status(task_id, status):
    """
    更新任务状态到数据库。

    :param task_id: 要更新的任务ID
    :param status: 新的状态值
    """
    try:
        status_conn = sqlite3.connect(DB, check_same_thread=False)
        with status_conn:
            status_conn.execute('UPDATE tasks SET status=? WHERE id=?', (status, task_id))
        logger.info(f"任务 {task_id} 的状态更新为 {status}")
    except sqlite3.Error as e:
        logger.error(f"更新任务 {task_id} 状态时数据库错误: {e}")


def worker():
    while True:
        task_id, photo_filename, audio_filename = task_queue.get()
        logger.info(f"开始处理任务: {task_id}")
        update_task_status(task_id, TASK_STATUS_RUNNING)
        try:
            base_args = [
                config.pythonPath, 'inference.py',
                '--driven_audio',
                audio_filename,
                '--source_image',
                photo_filename
            ]
            final_args = base_args + process_st_args(config.stArg)
            logger.debug(f"sadTalker full command: {final_args}")
            process = subprocess.run(
                final_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            if process.returncode == 0:
                output = process.stdout.decode('utf-8')
                match = re.search(r'./results/\d{4}_\d{2}_\d{2}_\d{2}\.\d{2}\.\d{2}\.mp4\n', output)
                if match:
                    result = match.group(0).strip().strip("./results/")
                    with conn as c:
                        c.execute('UPDATE tasks SET result=? WHERE id=?', (result, task_id))
                    update_task_status(task_id, TASK_STATUS_SUCCESS)
                    logger.info(f"任务成功完成: {task_id}, 结果: {result}")
                else:
                    logger.warning(f"任务完成但未找到匹配结果: {task_id}")
                    update_task_status(task_id, TASK_STATUS_MISSING)
            else:
                logger.error(f"任务失败，返回码: {process.returncode}, 错误信息: {process.stderr.decode('utf-8')}")
                update_task_status(task_id, TASK_STATUS_FAILED)
        except Exception as e:
            logger.exception(f"处理任务时出现异常: {task_id},错误: {e}")
            update_task_status(task_id, TASK_STATUS_FAILED)
        finally:
            task_queue.task_done()


app.register_blueprint(root)

if __name__ == '__main__':
    if not os.path.exists(config.uploadDir):
        os.makedirs(config.uploadDir)

    # 启动工作线程
    threading.Thread(target=worker, daemon=True).start()

    app.run(debug=bool(config.prod), host="0.0.0.0", port=int(config.apiPort))
