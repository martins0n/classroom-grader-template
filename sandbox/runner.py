"""Executes one notebook. Runs INSIDE the sandbox container, next to student code.

The result goes to the host as a single JSON document on stdout. Nothing else may reach
stdout or stderr: the host reads no files from the sandbox and treats this document as
untrusted, and notebook source or tracebacks must never end up in public logs.
"""
import json
import os
import sys


def extract_json_outputs(notebook):
    outputs = []
    for cell in notebook.cells:
        if cell.cell_type != "code":
            continue
        for output in cell.get("outputs", []):
            text = None
            if output.output_type in ("execute_result", "display_data"):
                text = output.get("data", {}).get("text/plain")
            elif output.output_type == "stream" and output.get("name") == "stdout":
                text = output.get("text")
            if text is None:
                continue
            try:
                outputs.append(json.loads(text))
            except (json.JSONDecodeError, TypeError):
                pass
    return outputs


def execute(path):
    import nbformat
    from nbclient.exceptions import CellExecutionError, CellTimeoutError
    from nbconvert.preprocessors import ExecutePreprocessor

    timeout = int(os.environ.get("SANDBOX_CELL_TIMEOUT", "3000"))
    notebook = nbformat.read(path, as_version=4)
    executor = ExecutePreprocessor(timeout=timeout, kernel_name="python3")

    def failed_cell():
        for index, cell in enumerate(notebook.cells):
            for output in cell.get("outputs", []):
                if output.get("output_type") == "error":
                    return index
        return None

    try:
        executor.preprocess(notebook, {"metadata": {"path": os.path.dirname(path) or "."}})
    except CellExecutionError as exc:
        return {"status": "error", "error_type": exc.ename, "cell_index": failed_cell()}
    except CellTimeoutError:
        return {"status": "error", "error_type": "CellTimeout", "cell_index": None}
    return {"status": "ok", "outputs": extract_json_outputs(notebook)}


def main():
    result_fd = os.dup(1)
    os.set_inheritable(result_fd, False)
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    try:
        result = execute(sys.argv[1])
    except BaseException as exc:  # noqa: BLE001 - the host must always get a verdict
        result = {"status": "error", "error_type": type(exc).__name__, "cell_index": None}
    with os.fdopen(result_fd, "w") as stream:
        json.dump(result, stream)


if __name__ == "__main__":
    main()
