#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地 HTTPS 服务器：为网页版 NFC 写卡提供安全上下文（Web NFC 必须 HTTPS）。

用法：
    python server.py            # 默认 8443 端口
    python server.py 9000       # 指定端口

手机和电脑连同一个 Wi-Fi，用安卓 Chrome/Edge 打开启动后打印的
https://电脑IP:端口 即可。首次访问出现"不安全"警告属正常
（自签名证书）：点"高级" -> "继续访问"。
"""
import json
import os
import re
import socket
import ssl
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8443
HERE = os.path.dirname(os.path.abspath(__file__))
CERT = os.path.join(HERE, 'cert.pem')
KEY = os.path.join(HERE, 'key.pem')

# 引入项目根目录的 songid，供 /resolve 接口复用解析逻辑
sys.path.insert(0, os.path.dirname(HERE))
from songid import extract_song_id  # noqa: E402

# /resolve 只允许解析网易云相关域名，避免被当成开放代理
ALLOWED_HOSTS = ('163cn.tv', 'music.163.com', 'y.music.163.com')


def list_local_ips():
    """拿到本机局域网 IPv4，方便打印给手机访问。"""
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith('127.'):
                ips.add(ip)
    except Exception:
        pass
    return sorted(ips)


def make_cert():
    """没有证书就自动生成自签名证书（优先 openssl，退而求其次用 cryptography）。"""
    if os.path.exists(CERT) and os.path.exists(KEY):
        return True
    print('未找到证书，自动生成自签名证书…')
    san = 'subjectAltName=DNS:localhost,IP:127.0.0.1'
    for ip in list_local_ips():
        san += ',IP:%s' % ip
    try:
        subprocess.run(
            ['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-sha256',
             '-days', '3650', '-nodes', '-keyout', KEY, '-out', CERT,
             '-subj', '/CN=nfc-local', '-addext', san],
            check=True, capture_output=True)
        print('已用 openssl 生成证书')
        return True
    except Exception:
        pass
    try:
        import ipaddress
        from datetime import datetime, timedelta, timezone

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'nfc-local')])
        sans = [x509.DNSName('localhost'), x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]
        for ip in list_local_ips():
            try:
                sans.append(x509.IPAddress(ipaddress.ip_address(ip)))
            except Exception:
                pass
        cert = (
            x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .sign(key, hashes.SHA256()))
        with open(KEY, 'wb') as f:
            f.write(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption()))
        with open(CERT, 'wb') as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        print('已用 cryptography 生成证书')
        return True
    except Exception:
        return False


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=HERE, **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/resolve':
            self._handle_resolve(parsed.query)
            return
        super().do_GET()

    def _handle_resolve(self, query):
        """POST 不方便在纯静态场景用，就用 GET /resolve?text=<分享内容>。

        服务器代替浏览器跟随短链跳转（浏览器有跨域限制），返回 {"id": "..."}
        或 {"error": "..."}。
        """
        text = (parse_qs(query).get('text') or [''])[0].strip()
        url_match = re.search(r'https?://\S+', text)
        host = urlparse(url_match.group(0)).hostname if url_match else None
        ok_host = host and any(
            host == h or host.endswith('.' + h) for h in ALLOWED_HOSTS)
        if not ok_host:
            payload = {'error': '只支持网易云相关链接（163cn.tv / music.163.com）'}
        else:
            try:
                song_id, err = extract_song_id(text, allow_network=True)
                payload = {'id': song_id} if song_id else {'error': err or '没有解析到歌曲ID'}
            except Exception as e:
                payload = {'error': '解析失败：%s' % e}
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print('[访问] %s' % (fmt % args))


def main():
    if not make_cert():
        print('无法生成证书。请先执行：  pip install cryptography  然后重新运行本脚本。')
        sys.exit(1)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)
    try:
        httpd = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    except OSError as e:
        print('端口 %d 被占用：%s。换个端口试试：python server.py 9000' % (PORT, e))
        sys.exit(1)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)

    print('=' * 62)
    print('网页版 NFC 写卡服务器已启动（HTTPS, 端口 %d）' % PORT)
    print('手机和电脑连同一个 Wi-Fi，用安卓 Chrome/Edge 访问：')
    for ip in list_local_ips():
        print('    https://%s:%d' % (ip, PORT))
    print('本机调试：  https://localhost:%d' % PORT)
    print('-' * 62)
    print('· 手机首次访问出现"不安全"警告 -> 点"高级" -> "继续访问"')
    print('· 若手机打不开：看 Windows 防火墙弹窗是否点了"允许"')
    print('· 写卡需要安卓 Chrome/Edge（iPhone 不支持网页写卡）')
    print('=' * 62)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')


if __name__ == '__main__':
    main()
