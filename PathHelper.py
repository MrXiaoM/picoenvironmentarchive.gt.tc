import os, sys

def get_working_dir():
    if getattr(sys, 'frozen', False):
        # 打包后环境：返回临时解压目录
        return os.path.dirname(sys.executable)
    else:
        # 开发环境：返回脚本所在目录
        return os.path.dirname(os.path.abspath(__file__))
