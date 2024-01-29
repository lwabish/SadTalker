from gradio_client import Client
import os


client = Client("http://10.10.10.105:7860")
# print(client.view_api())

# api不能用，一直没修复
# https://github.com/OpenTalker/SadTalker/issues/280
result = client.predict(
    os.path.join(os.path.expanduser("~"), "Downloads/image.jpg"),
    os.path.join(os.path.expanduser("~"), "Downloads/japanese.wav"),
    "full",
    True,
    True,
    2,
    "256",
    1,
    fn_index=1
)
print(result)
