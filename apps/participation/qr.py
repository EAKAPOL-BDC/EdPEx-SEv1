"""Local QR rendering. No third-party QR service receives bearer tokens."""
from .vendor.qrencoder import QRCode, QR8bitByte


def receipt_svg(url):
    if not isinstance(url, str) or len(url) > 500:
        raise ValueError('Invalid QR payload length.')
    qr = QRCode(version=None, errorCorrectLevel=0)  # automatic size, M correction
    qr.addData(QR8bitByte(url.encode('utf-8')))
    qr.make()
    n = qr.getModuleCount()
    path = ''.join(f'M{x+4} {y+4}h1v1h-1z' for y in range(n) for x in range(n) if qr.isDark(y,x))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n+8} {n+8}" '
            'shape-rendering="crispEdges"><rect width="100%" height="100%" fill="white"/>'
            f'<path fill="#24152f" d="{path}"/></svg>')
