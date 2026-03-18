
class CertObj:
    subject = None
    issuer = None
    serial_number = None
    valid_from = None
    valid_to = None
    version = None
    public_key = None
    signature_algorithm = None
    org_cert = None


    @classmethod
    def from_dict(cls, cert_dict):
        obj = cls()
        obj.subject = cert_dict.get('subject', '')
        obj.issuer = cert_dict.get('issuer', '')
        obj.serial_number = cert_dict.get('serial_number', '')
        obj.valid_from = cert_dict.get('valid_from', '')
        obj.valid_to = cert_dict.get('valid_to', '')
        obj.version = cert_dict.get('version', '')
        obj.public_key = cert_dict.get('public_key', None)
        obj.signature_algorithm = cert_dict.get('signature_algorithm', '')
        obj.org_cert = cert_dict.get('org_cert', None)
        return obj


class X509Obj:
    private_key = None
    public_key = None
    cert_list = []

    def __init__(self, cert_list, private_key=None, public_key=None):
        self.cert_list = cert_list
        self.private_key = private_key
        self.public_key = public_key