from rest_framework.views import exception_handler
from rest_framework.response import Response

def custom_exception_handler(exc, context):
    # Call REST framework's default exception handler first,
    # to get the standard error response.
    response = exception_handler(exc, context)

    # Now add the HTTP status code to the response.
    if response is not None:
        # Pylance type fix: explicitly create a new dict to ensure values can be Any
        if isinstance(response.data, dict):
            data = dict(response.data)
        elif isinstance(response.data, list):
            data = {'detail': response.data}
        elif response.data is None:
            data = {}
        else:
            data = {'detail': response.data}
            
        # Ensure there is a 'code' field
        if 'code' not in data:
            if hasattr(exc, 'default_code'):
                data['code'] = exc.default_code
            else:
                data['code'] = 'error'

        # Ensure there is a 'message' field (copy detail to message usually)
        if 'detail' in data:
            data['message'] = data['detail']
            # Optionally remove detail if you want a cleaner response, 
            # but keeping it for backward compatibility is fine.
            # del data['detail'] 
        elif 'message' not in data:
             # Handle cases like {"field": ["error"]}
             # convert to {"message": "field: error", ...}
             messages = []
             for key, value in data.items():
                 if key not in ['code', 'message']:
                     if isinstance(value, list):
                         messages.append(f"{key}: {'; '.join(str(v) for v in value)}")
                     else:
                         messages.append(f"{key}: {value}")
             if messages:
                 data['message'] = " | ".join(messages)
             else:
                 data['message'] = "Request failed"

        response.data = data

    return response
