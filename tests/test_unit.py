import os
from app import parse_python_file, analyze_directory


def test_parse_python_file_extracts_functions_classes_and_returns(tmp_path):
    code = (
        "class Greeter:\n"
        "    def say(self, name):\n"
        "        return f'Hi {name}'\n\n"
        "def add(a, b):\n"
        "    c = a + b\n"
        "    return c\n"
    )
    file_path = tmp_path / "sample.py"
    file_path.write_text(code, encoding="utf-8")

    functions, classes, content = parse_python_file(str(file_path))

    assert content.strip().startswith("class Greeter")
    func_names = {f["name"] for f in functions}
    class_names = {c["name"] for c in classes}

    assert "add" in func_names
    assert "Greeter" in class_names

    add_func = next(f for f in functions if f["name"] == "add")
    # Ensure a return statement was captured
    assert any("return" in r for r in add_func.get("returns", []))


def test_analyze_directory_builds_graph_recursively(tmp_path):
    # root file
    (tmp_path / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    # nested file
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "b.py").write_text("class C:\n    pass\n", encoding="utf-8")

    result = analyze_directory(str(tmp_path))
    nodes = result["nodes"]
    edges = result["edges"]

    # We expect two file nodes and corresponding function/class nodes
    file_nodes = [n for n in nodes if n["type"] == "file"]
    assert len(file_nodes) == 2
    assert any(n["name"].endswith("a.py") for n in file_nodes)
    assert any("pkg/" in n["name"] or n["name"].startswith("pkg/") for n in file_nodes)

    # There should be at least one function and one class node
    assert any(n["type"] == "function" for n in nodes)
    assert any(n["type"] == "class" for n in nodes)
    # And edges must connect files to their members
    assert any(e["source"].endswith("a.py") for e in edges)

