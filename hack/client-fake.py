from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
import time
import base64


# 从文件中读取并解码公钥
def load_public_key(file_path):
    with open(file_path, 'r') as public_file:
        public_key_encoded = public_file.read()
        public_key_der = base64.b64decode(public_key_encoded)
        return RSA.import_key(public_key_der)


public_key = load_public_key('../certs/public.pem')
cipher_rsa = PKCS1_v1_5.new(public_key)


def create_ticket(openid):
    # 生成时间戳
    timestamp = str(int(time.time()))

    # 加密openid和时间戳
    data_to_encrypt = f'{openid}{timestamp}'.encode('utf-8')
    encrypted_data = cipher_rsa.encrypt(data_to_encrypt)

    return encrypted_data


# 假设这是客户端的openid
client_openid = 'some_openid'

# 创建ticket
ticket = create_ticket(client_openid)

# 这里应该是发送请求到服务端的代码
# 为了演示，我们只是打印出来
print("openid:", client_openid)
print("ticket:", base64.b64encode(ticket))
