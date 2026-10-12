def encode(text):
    result = []
    for char in text:
        if result and result[-1][0] == char:
            result[-1] = (char, result[-1][1] + 1)
        else:
            result.append((char, 1))
    return result


def decode(runs):
    result = []
    for char, count in runs:
        if (
            not isinstance(char, str)
            or len(char) != 1
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count <= 0
        ):
            raise ValueError("invalid run")
        result.append(char * count)
    return "".join(result)
