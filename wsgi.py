import os
import sys
from dotenv import load_dotenv

# 加载.flaskenv文件中的环境变量
dotenv_path = os.path.join(os.path.dirname(__file__), '.flaskenv')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)

# 导入应用实例
from dgbygapp import create_app

# 创建应用实例
app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True) 