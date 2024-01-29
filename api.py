from flask import Flask, request, jsonify, abort
import os
import subprocess
import threading
import re
import sqlite3
import uuid
import logging
from queue import Queue

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads/'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp3', 'wav'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# 创建一个队列
task_queue = Queue()
# 创建数据库和表（如果不存在的话）
conn = sqlite3.connect('tasks.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS tasks
             (id TEXT PRIMARY KEY, result TEXT, status TEXT)''')
conn.commit()

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s')
logger = logging.getLogger(__name__)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'photo' not in request.files or 'audio' not in request.files:
        return jsonify(error="No photo/audio part in the request"), 400
    photo = request.files['photo']
    audio = request.files['audio']
    if photo.filename == '' or audio.filename == '':
        return jsonify(error="No selected file"), 400
    if photo and allowed_file(photo.filename) and audio and allowed_file(audio.filename):
        task_id = str(uuid.uuid4())  # 生成唯一ID
        photo_filename = os.path.join(app.config['UPLOAD_FOLDER'], photo.filename)
        audio_filename = os.path.join(app.config['UPLOAD_FOLDER'], audio.filename)
        photo.save(photo_filename)
        audio.save(audio_filename)
        # 将任务添加到队列
        task_queue.put((task_id, photo_filename, audio_filename))
        c.execute('INSERT INTO tasks (id, result, status) VALUES (?,?,?)', (task_id, None, "pending"))
        conn.commit()
        return jsonify(task_id=task_id), 202
    else:
        return jsonify(error="File type not allowed"), 400


@app.route('/status/<task_id>', methods=['GET'])
def get_status(task_id):
    c.execute('SELECT result, status FROM tasks WHERE id=?', (task_id,))
    task = c.fetchone()
    if task:
        return jsonify(id=task_id, result=task[0], status=task[1])
    else:
        abort(404)


def update_task_status(task_id, status):
    """
    更新任务状态到数据库。

    :param task_id: 要更新的任务ID
    :param status: 新的状态值
    """
    try:
        c.execute('UPDATE tasks SET status=? WHERE id=?', (status, task_id))
        conn.commit()
        logger.info(f"任务 {task_id} 的状态更新为 {status}")
    except sqlite3.Error as e:
        logger.error(f"更新任务 {task_id} 状态时数据库错误: {e}")


def worker():
    while True:
        task_id, photo_filename, audio_filename = task_queue.get()
        logger.info(f"开始处理任务: {task_id}")
        try:
            # 调用subprocess（假设的命令和参数）
            process = subprocess.run([
                # todo: python path
                '/root/miniconda3/envs/sadtalker/bin/python', 'inference.py',
                '--driven_audio',
                audio_filename,
                '--source_image',
                photo_filename,
                '--enhancer',
                "gfpgan",
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if process.returncode == 0:
                output = process.stdout.decode('utf-8')
                match = re.search(r'./results/\d{4}_\d{2}_\d{2}_\d{2}\.\d{2}\.\d{2}\.mp4\n', output)
                if match:
                    result = match.group(0).strip()
                    c.execute('UPDATE tasks SET result=? WHERE id=?', (result, task_id))
                    conn.commit()
                    update_task_status(task_id, "success")
                    logger.info(f"任务成功完成: {task_id}, 结果: {result}")
                else:
                    logger.warning(f"任务完成但未找到匹配结果: {task_id}")
                    update_task_status(task_id, "missing_result")
            else:
                logger.error(f"任务失败，返回码: {process.returncode}, 错误信息: {process.stderr.decode('utf-8')}")
                update_task_status(task_id, "failed")
        except Exception as e:
            logger.exception(f"处理任务时出现异常: {task_id}")
            update_task_status(task_id, "failed")
        finally:
            task_queue.task_done()


if __name__ == '__main__':
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    # 启动工作线程
    threading.Thread(target=worker, daemon=True).start()

    app.run(debug=True, host="0.0.0.0")
