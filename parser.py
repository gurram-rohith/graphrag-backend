import os
import ast
from neo4j import GraphDatabase
from openai import OpenAI
import config
from concurrent.futures import ThreadPoolExecutor

# Global Nvidia API Client for Embeddings and Summaries
nvidia_client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=config.NVIDIA_API_KEY
)

def generate_summary_with_llama(content: str) -> str:
    try:
        truncated_content = content[:6000] 
        prompt = f"Summarize the purpose and functionality of this code in 3 sentences:\n\n{truncated_content}"
        
        completion = nvidia_client.chat.completions.create(
            model=config.NVIDIA_CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=200
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating summary: {e}")
        return "No summary available."

def extract_ast_dependencies(file_path: str):
    """Parses Python AST if it's a .py file. Otherwise just returns the raw text."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        functions = []
        calls = []
        
        # Only attempt AST parsing if it's a Python file
        if file_path.endswith('.py'):
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    functions.append(node.name)
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name): 
                        calls.append(node.func.id)
                    elif isinstance(node.func, ast.Attribute): 
                        calls.append(node.func.attr)
                    
        return content, functions, calls
    except Exception as e:
        return "", [], []

def process_single_file(file_path, owner_id, project_id):
    """Helper to process one file entirely."""
    content, functions, calls = extract_ast_dependencies(file_path)
    if not content.strip(): 
        return None
    
    summary = generate_summary_with_llama(content)
    return {
        "file_path": file_path,
        "file_name": os.path.basename(file_path),
        "summary": summary,
        "functions": functions,
        "calls": calls
    }

def run_parsing_pipeline(file_list, owner_id, project_id):
    processed = 0
    errors = 0
    
    # 1. Accept Python AND JavaScript/TypeScript/Web files
    allowed_extensions = ('.py', '.js', '.jsx', '.ts', '.tsx', '.json')
    target_files = [f for f in file_list if f.endswith(allowed_extensions)]
    
    if not target_files:
        print("DEBUG: No supported source files found.")
        return {"processed": 0, "errors": 0}

    # Process files concurrently for fast Llama summarization
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda f: process_single_file(f, owner_id, project_id), target_files))
    
    valid_data = [r for r in results if r]
    
    if not valid_data:
        return {"processed": 0, "errors": errors}

    # 2. Nvidia Cloud Batch Embedding (1024 dimensions)
    summaries = [d["summary"] for d in valid_data]
    embeddings = []
    
    batch_size = 32
    for i in range(0, len(summaries), batch_size):
        batch = summaries[i:i + batch_size]
        try:
            response = nvidia_client.embeddings.create(
                input=batch,
                model=config.NVIDIA_EMBEDDING_MODEL,
                extra_body={"input_type": "passage"} # Tells Nvidia this is document data to index
            )
            embeddings.extend([item.embedding for item in response.data])
        except Exception as e:
            print(f"ERROR: Failed to generate Nvidia embeddings for batch {i}: {e}")
            return {"processed": 0, "errors": len(valid_data)}

    # 3. Bulk DB Writes to Neo4j
    driver = GraphDatabase.driver(config.URI, auth=(config.USER, config.PASSWORD))
    with driver.session() as session:
        for i, data in enumerate(valid_data):
            try:
                session.run("""
                    MERGE (f:File {name: $name, owner_id: $owner_id, project_id: $project_id})
                    SET f.summary = $summary, f.summary_embedding = $embedding, f:Entity
                """, name=data["file_name"], owner_id=owner_id, project_id=project_id, 
                     summary=data["summary"], embedding=embeddings[i])
                
                for func in data["functions"]:
                    session.run("""
                        MATCH (f:File {name: $name, owner_id: $owner_id, project_id: $project_id})
                        MERGE (func:Entity {name: $func_name, owner_id: $owner_id, project_id: $project_id})
                        SET func:Function MERGE (f)-[:CONTAINS]->(func)
                    """, name=data["file_name"], owner_id=owner_id, project_id=project_id, func_name=func)
                
                for call in data["calls"]:
                    session.run("""
                        MATCH (f:File {name: $name, owner_id: $owner_id, project_id: $project_id})
                        MERGE (callee:Entity {name: $call_name, owner_id: $owner_id, project_id: $project_id})
                        MERGE (f)-[:CALLS]->(callee)
                    """, name=data["file_name"], owner_id=owner_id, project_id=project_id, call_name=call)
                
                processed += 1
            except Exception as e:
                print(f"Database error for {data['file_name']}: {e}")
                errors += 1
                
    driver.close()
    return {"processed": processed, "errors": errors}