import os
from neo4j import GraphDatabase
from openai import OpenAI
import config
from ast_adapter import UniversalParser, LANGUAGE_MAP

nvidia_client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=config.NVIDIA_API_KEY
)

def run_parsing_pipeline(file_list, owner_id, project_id):
    target_files = [f for f in file_list if os.path.splitext(f)[1].lower() in LANGUAGE_MAP]
    
    if not target_files:
        return {"processed": 0, "errors": 0}

    all_files = []
    all_functions = []
    all_calls = []
    embedding_payloads = [] # Maintains order for batch embedding

    # 1. Local CPU Extraction (Lightning Fast, no LLM bottlenecks)
    for file_path in target_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            ext = os.path.splitext(file_path)[1].lower()
            file_name = os.path.basename(file_path)
            parser = UniversalParser(ext)
            
            file_chunk, functions, calls = parser.parse_file(content, file_name)
            
            file_data = {"name": file_name, "chunk_text": file_chunk}
            all_files.append(file_data)
            embedding_payloads.append(file_data)
            
            for func in functions:
                func["file_name"] = file_name
                all_functions.append(func)
                embedding_payloads.append(func)
                
            for call in calls:
                call["file_name"] = file_name
                all_calls.append(call)
                
        except Exception as e:
            print(f"Extraction error on {file_path}: {e}")

    # 2. Batch Embedding Generation (1 API Call per 32 chunks)
    batch_size = 32
    for i in range(0, len(embedding_payloads), batch_size):
        batch = embedding_payloads[i:i + batch_size]
        texts_to_embed = [item["chunk_text"] for item in batch]
        
        try:
            response = nvidia_client.embeddings.create(
                input=texts_to_embed,
                model=config.NVIDIA_EMBEDDING_MODEL,
                extra_body={"input_type": "passage"}
            )
            for item, data in zip(batch, response.data):
                item["embedding"] = data.embedding
        except Exception as e:
            print(f"ERROR: Embedding generation failed for batch {i}: {e}")
            return {"processed": 0, "errors": len(target_files)}

    # 3. Massive DB Write via UNWIND
    driver = GraphDatabase.driver(config.URI, auth=(config.USER, config.PASSWORD))
    with driver.session() as session:
        try:
            # Insert Files
            session.run("""
                UNWIND $files AS f
                MERGE (file:Entity {name: f.name, owner_id: $owner_id, project_id: $project_id})
                SET file:File, file.chunk = f.chunk_text, file.embedding = f.embedding
            """, files=all_files, owner_id=owner_id, project_id=project_id)

            # Insert Functions
            session.run("""
                UNWIND $functions AS fn
                MATCH (file:Entity:File {name: fn.file_name, owner_id: $owner_id, project_id: $project_id})
                MERGE (func:Entity {name: fn.name, owner_id: $owner_id, project_id: $project_id})
                SET func:Function, func.chunk = fn.chunk_text, func.embedding = fn.embedding
                MERGE (file)-[:CONTAINS]->(func)
            """, functions=all_functions, owner_id=owner_id, project_id=project_id)

            # Insert Calls
            session.run("""
                UNWIND $calls AS c
                MATCH (file:Entity:File {name: c.file_name, owner_id: $owner_id, project_id: $project_id})
                
                // If caller is global, the file is the caller. Otherwise, find the caller function.
                OPTIONAL MATCH (caller:Entity:Function {name: c.caller, owner_id: $owner_id, project_id: $project_id})
                WITH c, file, coalesce(caller, file) AS actual_caller, $owner_id AS oid, $project_id AS pid
                
                MERGE (callee:Entity {name: c.callee, owner_id: oid, project_id: pid})
                MERGE (actual_caller)-[:CALLS]->(callee)
            """, calls=all_calls, owner_id=owner_id, project_id=project_id)
            
        except Exception as e:
            print(f"Database bulk insert error: {e}")
            return {"processed": 0, "errors": len(target_files)}
            
    driver.close()
    return {"processed": len(target_files), "errors": 0}