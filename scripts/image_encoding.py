"""Page image codec policy. Same values as core/ImageEncoding; previews use PNG."""
KEYS = ('format', 'png_compression', 'tiff_compression', 'jpeg_quality')

def resolve(value=None, overrides=None):
    config = dict(value or {})
    if overrides and overrides.get('format') is not None and overrides['format'] != config.get('format', 'png'):
        config = {}
    config.update({k: v for k, v in (overrides or {}).items() if v is not None})
    fmt = config.get('format', 'png')
    if fmt not in ('png', 'tiff', 'jpeg'):
        raise ValueError('Invalid image format')
    key = {'png': 'png_compression', 'tiff': 'tiff_compression', 'jpeg': 'jpeg_quality'}[fmt]
    if set(config) - {'format', key}:
        raise ValueError('Unrelated or unknown image encoding options: ' + ', '.join(sorted(set(config) - {'format', key})))
    number = config.get(key, {'png': 6, 'tiff': 'deflate', 'jpeg': 95}[fmt])
    if fmt == 'tiff':
        if number not in ('none', 'lzw', 'deflate'):
            raise ValueError('Invalid TIFF compression')
    elif type(number) is not int or not (0 if fmt == 'png' else 1) <= number <= (9 if fmt == 'png' else 100):
        raise ValueError('Invalid image compression level/quality')
    return {'format': fmt, key: number}

def arguments(value):
    value = resolve(value)
    return [part for k, v in value.items() for part in ('--image-format' if k == 'format' else '--' + k.replace('_', '-'), str(v))]

def suffix(value):
    return {'png': '.png', 'tiff': '.tif', 'jpeg': '.jpg'}[value['format']]

def save(image, path, value, dpi):
    fmt = value['format']
    options = {'dpi': (dpi, dpi)}
    if fmt == 'png':
        options['compress_level'] = value['png_compression']
    elif fmt == 'tiff':
        options['compression'] = {'none': 'raw', 'lzw': 'tiff_lzw', 'deflate': 'tiff_adobe_deflate'}[value['tiff_compression']]
    else:
        options['quality'] = value['jpeg_quality']
        options['subsampling'] = 0
    image.save(path, format={'png': 'PNG', 'tiff': 'TIFF', 'jpeg': 'JPEG'}[fmt], **options)
