from markdown import headings


def test_headings():
    assert headings("# A\n  ### B ###\n#\n#tag\n####### X\n    # indent") == [
        (1, "A"),
        (3, "B"),
        (1, ""),
    ]


def test_fences():
    assert headings("# A\n```py\n## hidden\n```\n~~~\n# hidden\n~~~\n## B") == [
        (1, "A"),
        (2, "B"),
    ]


def test_fence_length():
    assert headings("````\n# hidden\n```\n# still hidden\n````\n# visible") == [
        (1, "visible")
    ]


def test_hashes():
    assert headings("## C#\n# x#\n# 你好  ##") == [(2, "C#"), (1, "x#"), (1, "你好")]
