from flask import Flask
from dgbygapp.config import Config
from flask_mail import Mail
import logging

mail = Mail()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    mail.init_app(app)

    # 添加基础日志配置
    logging.basicConfig(level=logging.INFO,
                       format='%(asctime)s - %(levelname)s - %(message)s')

    from dgbygapp.routes import init_routes
    init_routes(app)
    import os
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    return app