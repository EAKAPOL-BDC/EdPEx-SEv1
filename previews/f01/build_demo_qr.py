from pathlib import Path
from reportlab.graphics.barcode.qrencoder import QRCode, QR8bitByte
payload='NEXORA|DEMO-NOT-VALID|NXR-DEMO-F01-2568-0001|F01|AY2568'
qr=QRCode(version=4,errorCorrectLevel=0)
qr.addData(QR8bitByte(payload))
qr.make()
n=qr.getModuleCount(); size=n+8
path=''.join(f'M{x+4},{y+4}h1v1h-1z' for y in range(n) for x in range(n) if qr.isDark(y,x))
svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size*8}" height="{size*8}" role="img" aria-label="DEMO receipt QR code" shape-rendering="crispEdges"><title>DEMO — NOT VALID</title><rect width="{size}" height="{size}" fill="white"/><path d="{path}" fill="black"/></svg>'
Path('work/Nexora/previews/f01/demo-qr.svg').write_text(svg,encoding='utf-8')
print('QR generated with reportlab; payload:',payload)

