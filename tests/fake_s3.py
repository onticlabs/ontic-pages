"""An in-memory stand-in for the few boto3 S3 calls ontic-pages makes."""

from __future__ import annotations

import hashlib
import io
import re
from urllib.parse import quote, urlencode

from botocore.exceptions import ClientError


def _error(code: str, op: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, op)


def _etag(data: bytes) -> str:
    return f'"{hashlib.md5(data).hexdigest()}"'


class FakeS3:
    def __init__(self):
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.calls: list[str] = []
        self.upload_base = "http://uploads.invalid"

    def put_object(self, Bucket, Key, Body, ContentType="application/octet-stream"):
        self.calls.append("put_object")
        data = Body if isinstance(Body, bytes) else Body.read()
        self.objects[(Bucket, Key)] = (data, ContentType)
        return {"ETag": _etag(data)}

    def copy_object(self, Bucket, Key, CopySource, ContentType=None, MetadataDirective=None):
        self.calls.append("copy_object")
        src = (CopySource["Bucket"], CopySource["Key"])
        if src not in self.objects:
            raise _error("NoSuchKey", "CopyObject")
        data, ctype = self.objects[src]
        self.objects[(Bucket, Key)] = (data, ContentType or ctype)
        return {"CopyObjectResult": {"ETag": _etag(data)}}

    def head_object(self, Bucket, Key):
        self.calls.append("head_object")
        if (Bucket, Key) not in self.objects:
            raise _error("404", "HeadObject")
        data = self.objects[(Bucket, Key)][0]
        return {"ContentLength": len(data), "ETag": _etag(data)}

    def get_object(self, Bucket, Key, Range=None):
        self.calls.append("get_object")
        if (Bucket, Key) not in self.objects:
            raise _error("NoSuchKey", "GetObject")
        data, ctype = self.objects[(Bucket, Key)]
        out = {"ContentType": ctype, "ETag": _etag(data)}
        if Range:
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", Range)
            start = int(m.group(1)) if m.group(1) else len(data) - int(m.group(2))
            end = int(m.group(2)) if m.group(1) and m.group(2) else len(data) - 1
            if start >= len(data):
                raise _error("InvalidRange", "GetObject")
            end = min(end, len(data) - 1)
            out["ContentRange"] = f"bytes {start}-{end}/{len(data)}"
            data = data[start : end + 1]
        out.update(Body=io.BytesIO(data), ContentLength=len(data))
        return out

    def generate_presigned_url(self, ClientMethod, Params, ExpiresIn):
        """A URL on `upload_base` (helpers.upload_server stores PUTs to it here and answers GETs
        from here), with what was signed in the query."""
        self.calls.append("generate_presigned_url")
        if ClientMethod == "get_object":
            assert set(Params) == {"Bucket", "Key"}
            query = urlencode({"get": 1, "expires": ExpiresIn})
            return f"{self.upload_base}/{Params['Bucket']}/{quote(Params['Key'])}?{query}"
        assert ClientMethod == "put_object" and set(Params) == {"Bucket", "Key", "ContentType"}
        query = urlencode({"ct": Params["ContentType"], "expires": ExpiresIn})
        return f"{self.upload_base}/{Params['Bucket']}/{quote(Params['Key'])}?{query}"

    def list_objects_v2(self, Bucket, Prefix="", Delimiter="", ContinuationToken=None):
        self.calls.append("list_objects_v2")
        keys = sorted(k for b, k in self.objects if b == Bucket and k.startswith(Prefix))
        contents, prefixes = [], set()
        for key in keys:
            rest = key[len(Prefix) :]
            if Delimiter and Delimiter in rest:
                prefixes.add(Prefix + rest.split(Delimiter)[0] + Delimiter)
            else:
                contents.append({"Key": key, "Size": len(self.objects[(Bucket, key)][0])})
        return {
            "Contents": contents,
            "CommonPrefixes": [{"Prefix": p} for p in sorted(prefixes)],
            "IsTruncated": False,
        }
