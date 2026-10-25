import os
from flask import Flask, jsonify, send_from_directory
from sqlalchemy.exc import OperationalError
from config import Config
from extensions import db, jwt, cors

from routes.auth       import auth_bp
from routes.files      import files_bp
from routes.club       import club_bp


def create_app(config_class=Config):
    app = Flask(
        __name__,
        static_folder=os.path.join(os.path.dirname(__file__), '..', 'frontend'),
        static_url_path='',
    )
    app.config.from_object(config_class)

    # 初始化扩展
    db.init_app(app)
    jwt.init_app(app)
    cors.init_app(app, resources={r'/api/*': {'origins': '*'}})

    # 注册蓝图
    for bp in (auth_bp, files_bp, club_bp):
        app.register_blueprint(bp)

    # 确保上传目录存在
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # 错误处理
    @app.errorhandler(404)
    def not_found(e):
        return jsonify(msg='资源不存在'), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify(msg='不允许的请求方法'), 405

    @app.errorhandler(413)
    def request_entity_too_large(e):
        return jsonify(msg='文件超出最大限制（2GB）'), 413

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify(msg='服务器内部错误'), 500

    @app.errorhandler(OperationalError)
    def database_unavailable(e):
        return jsonify(msg='数据库暂时不可用，请检查数据库配置或先运行初始化脚本'), 503

    # 前端 SPA 路由：非 /api 的请求一律返回 index.html
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve_frontend(path):
        if path.startswith('api/'):
            return jsonify(msg='接口不存在'), 404
        full_path = os.path.join(app.static_folder, path)
        if path and os.path.exists(full_path):
            return send_from_directory(app.static_folder, path)
        return send_from_directory(app.static_folder, 'index.html')

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=False)
