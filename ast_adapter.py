from tree_sitter import Parser, Language, Query
import tree_sitter_javascript as ts_js
import tree_sitter_python as ts_python
import tree_sitter_java as ts_java
import tree_sitter_c as ts_c
import tree_sitter_cpp as ts_cpp

LANGUAGE_MAP = {
    ".js": {
        "lang": ts_js.language(),
        "call_query": "(call_expression function: (identifier) @call_name)",
        "func_types": ["function_declaration", "arrow_function", "function"]
    },
    ".py": {
        "lang": ts_python.language(),
        "call_query": "(call function: (identifier) @call_name)",
        "func_types": ["function_definition"]
    },
    ".java": {
        "lang": ts_java.language(),
        "call_query": "(method_invocation name: (identifier) @call_name)",
        "func_types": ["method_declaration"]
    },
    ".c": {
        "lang": ts_c.language(),
        "call_query": "(call_expression function: (identifier) @call_name)",
        "func_types": ["function_definition"]
    },
    ".cpp": {
        "lang": ts_cpp.language(),
        "call_query": "(call_expression function: (identifier) @call_name)",
        "func_types": ["function_definition"]
    }
}

class UniversalParser:
    def __init__(self, ext):
        if ext not in LANGUAGE_MAP:
            raise ValueError(f"Unsupported extension: {ext}")
            
        config = LANGUAGE_MAP[ext]
        self.language = Language(config["lang"])
        self.parser = Parser(self.language)
        self.call_query_string = config["call_query"]
        self.func_types = config["func_types"]

    def _get_parent_func_name(self, node):
        current = node.parent
        while current:
            if current.type in self.func_types:
                name_node = current.child_by_field_name("name")
                if name_node:
                    return name_node.text.decode("utf8")
            current = current.parent
        return "global"

    def parse_file(self, source_code: str, file_name: str):
        tree = self.parser.parse(bytes(source_code, "utf8"))
        
        # Correctly execute the query using the modern API (No QueryCursor)
        call_query = Query(self.language, self.call_query_string)
        call_results = call_query.captures(tree.root_node)
        
        calls = []
        if isinstance(call_results, dict):
            nodes_to_process = call_results.get("call_name", [])
        else:
            nodes_to_process = [item[0] for item in call_results if isinstance(item, tuple) and item[1] == "call_name"]

        if not isinstance(nodes_to_process, list):
            nodes_to_process = [nodes_to_process]

        for node in nodes_to_process:
            if not node: continue
            call_name = node.text.decode("utf8")
            parent_func = self._get_parent_func_name(node)
            calls.append({"caller": parent_func, "callee": call_name})

        functions = []
        def walk_tree(node):
            if node.type in self.func_types:
                name_node = node.child_by_field_name("name")
                func_name = name_node.text.decode("utf8") if name_node else "anonymous"
                raw_text = node.text.decode("utf8")[:500] 
                
                chunk_text = (
                    f"Type: Function\n"
                    f"File: {file_name}\n"
                    f"Name: {func_name}\n"
                    f"Logic Snippet:\n{raw_text}..."
                )
                
                functions.append({
                    "name": func_name,
                    "chunk_text": chunk_text
                })
            for child in node.children:
                walk_tree(child)
                
        walk_tree(tree.root_node)
        
        file_chunk = (
            f"Type: Source File\n"
            f"File: {file_name}\n"
            f"Contains Functions: {', '.join([f['name'] for f in functions])}"
        )

        return file_chunk, functions, calls