import json


class ProfilePayload:
    def __init__(self, **kwargs):
        self.data = kwargs

    def to_dict(self):
        """Convert all JSON fields properly"""
        out = {}
        for key, value in self.data.items():
            if isinstance(value, (dict, list)):
                out[key] = json.dumps(value)
            else:
                out[key] = value
        return out
