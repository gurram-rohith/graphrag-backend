from tree_sitter import Parser, Language
import tree_sitter_javascript as ts_js
import tree_sitter_python as ts_python
import tree_sitter_java as ts_java
import tree_sitter_c as ts_c
import tree_sitter_cpp as ts_cpp

LANGUAGE_MAP = {
    ".js": {
        "lang": ts_js.language(),
        "func_types": ["function_declaration", "arrow_function", "function"]
    },
    ".py": {
        "lang": ts_python.language(),
        "func_types": ["function_definition"]
    },
    ".java": {
        "lang": ts_java.language(),
        "func_types": ["method_declaration"]
    },
    ".c": {
        "lang": ts_c.language(),
        "func_types": ["function_definition"]
    },
    ".cpp": {
        "lang": ts_cpp.language(),
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
        self.func_types = config["func_types"]

    def parse_file(self, source_code: str, file_name: str):
        tree = self.parser.parse(bytes(source_code, "utf8"))
        
        functions = []
        calls = []
        
        def walk_tree(node, current_func="global"):
            # 1. Check if we are entering a new function
            if node.type in self.func_types:
                name_node = node.child_by_field_name("name") or node.child_by_field_name("declarator")
                
                # Handle nested C/C++ declarators safely
                if name_node and name_node.type == 'function_declarator':
                    name_node = name_node.child_by_field_name("declarator")
                    
                func_name = name_node.text.decode("utf8") if name_node else "anonymous"
                current_func = func_name
                
                # Store the function chunk
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

            # 2. Check if this node is a function call
            if node.type in ["call_expression", "call", "method_invocation"]:
                target_node = node.child_by_field_name("function") or node.child_by_field_name("name")
                if target_node:
                    call_name = target_node.text.decode("utf8")
                    calls.append({"caller": current_func, "callee": call_name})

            # 3. Recurse into children, passing down the current function context
            for child in node.children:
                walk_tree(child, current_func)
                
        walk_tree(tree.root_node)
        
        file_chunk = (
            f"Type: Source File\n"
            f"File: {file_name}\n"
            f"Contains Functions: {', '.join([f['name'] for f in functions])}"
        )

        return file_chunk, functions, calls