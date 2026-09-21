"""Keep new production collections and preview collections in separate realms."""
from django.conf import settings
from . import services


def data_kind():
    return 'real' if getattr(settings, 'PRODUCTION', False) else 'synthetic'


def creation_contract():
    kind = data_kind()
    realm = 'live' if kind == 'real' else 'test'
    services._realm(realm)
    return kind, realm


def confirm_label():
    if data_kind() == 'real':
        return 'ตรวจข้อมูลแล้ว ยืนยันสร้างรอบใช้งานจริง ซึ่งยังไม่เปิดรับจนกว่าจะสั่งเปิดรับและเผยแพร่ / I reviewed this real collection; opening and publication are separate actions'
    return 'ตรวจข้อมูลแล้ว ยืนยันสร้างรอบทดสอบด้วยข้อมูลสมมุติ ซึ่งยังไม่เปิดรับ / I reviewed this synthetic test collection; it will not open automatically'


def setup_notice():
    if data_kind() == 'real':
        return 'รอบใช้งานจริง · สร้างแล้วอยู่สถานะพร้อม ยังไม่เปิดรับและยังไม่เผยแพร่ / Real collection. Creation does not open or publish it.'
    return 'รอบทดสอบใหม่ ใช้ข้อมูลสมมุติ สร้างแล้วอยู่สถานะพร้อม ยังไม่เปิดรับและยังไม่เผยแพร่ / New synthetic test collection. Creation does not open or publish it.'
