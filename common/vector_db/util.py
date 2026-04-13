import ast
from typing import Dict, Any


def flatten_to_strings(data,skip_keys = None):
    if skip_keys is None:
        skip_keys  = ['embedding']

    if isinstance(data,dict):
        return {
            key:value if key in skip_keys else str(value)
            for key, value in data.items()
        }
    else:
        return str(data)

def restore_string_values(data:Dict[str,Any])->Dict[str,Any]:
    if not isinstance(data,dict):
        raise TypeError("data must be a dict")

    def try_convert(value:str) -> Any:
        if not isinstance(value,str):
            return value

        if value == 'True':
            return True
        if value == 'False':
            return False
        if value == 'None':
            return None

        try:
            converted = ast.literal_eval(value)
            if isinstance(converted,(list,dict,tuple,int,float,bool)) or converted is None:
                return converted
        except (ValueError, SyntaxError):
            pass

        return value

    return {key:try_convert(value) for key,value in data.items()}