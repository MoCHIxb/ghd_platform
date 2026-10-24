import os
import uuid
from werkzeug.utils import secure_filename
from config import Config


def allowed_file(filename: str) -> bool:
    """检查文件扩展名是否在允许列表中"""
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in Config.allowed_extensions()


def get_file_type(ext: str) -> str:
    """根据扩展名判断文件类型。"""
    ext = ext.lower()
    if ext in Config.ALLOWED_AUDIO:
        return 'audio'
    if ext in Config.ALLOWED_VIDEO:
        return 'video'
    if ext in Config.ALLOWED_IMAGE:
        return 'image'
    if ext in Config.ALLOWED_DOCUMENT:
        return 'document'
    return 'unknown'


def save_uploaded_file(file_storage, upload_folder: str) -> dict:
    """
    将 werkzeug FileStorage 保存到 upload_folder，使用 UUID 命名。
    返回 dict: {filename, original_name, file_ext, file_type, file_size, storage_path}
    """
    original_name = secure_filename(file_storage.filename)
    ext = original_name.rsplit('.', 1)[1].lower() if '.' in original_name else ''
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(upload_folder, exist_ok=True)
    storage_path = os.path.join(upload_folder, unique_name)
    file_storage.save(storage_path)
    file_size = os.path.getsize(storage_path)
    return {
        'filename':      unique_name,
        'original_name': original_name,
        'file_ext':      ext,
        'file_type':     get_file_type(ext),
        'file_size':     file_size,
        'storage_path':  storage_path,
    }


def delete_file_from_disk(storage_path: str) -> bool:
    """删除磁盘文件，成功返回 True"""
    try:
        if storage_path and os.path.exists(storage_path):
            os.remove(storage_path)
            return True
    except OSError:
        pass
    return False


def format_file_size(size_bytes: int) -> str:
    """将字节数格式化为可读字符串"""
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
