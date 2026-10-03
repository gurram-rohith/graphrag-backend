from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import ingest
import parser
import query_engine
import config
import os
import shutil
import json
from neo4j import GraphDatabase
from openai import OpenAI
from fastapi.responses import StreamingResponse

app = FastAPI()

# Enable CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Nvidia API Client for Embeddings and Completions
print("Initializing Nvidia API Client...")
nvidia_client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=config.NVIDIA_API_KEY
)
print("Client initialized successfully!")

# Global in-memory status tracker for ingestion
ingestion_status = {
    "status": "idle",
    "url": None,
    "processed_files": 0,
    "errors": 0,
    "error_message": None
}

# --- Pydantic Data Models ---

class RepoRequest(BaseModel):
    url: str
    owner_id: str
    project_id: str

class QueryRequest(BaseModel):
    question: str
    owner_id: str
    project_id: str

# --- Background Work Pipeline ---

def run_background_pipeline(url: str, owner_id: str, project_id: str):
    global ingestion_status
    ingestion_status = {
        "status": "processing",
        "url": url,
        "processed_files": 0,
        "errors": 0,
        "error_message": None
    }
    
    temp_dir = None
    try:
        # 1. Clone into isolated directory
        file_list, temp_dir = ingest.ingest_repository(url)
        print(f"DEBUG: Clone successful. Total logic files detected: {len(file_list)}")
        
        # 2. Resolve relative paths to absolute paths
        absolute_file_list = [
            f if os.path.isabs(f) else os.path.abspath(os.path.join(temp_dir, f))
            for f in file_list
        ]
        
        # 3. Clean Project Data and Ensure Vector Index
        driver = GraphDatabase.driver(config.URI, auth=(config.USER, config.PASSWORD))
        with driver.session() as session:
            # Drop obsolete index from previous migrations if still present
            session.run("DROP INDEX file_summary_index IF EXISTS")

            # Wipe only data for this owner and project
            session.run("""
                MATCH (n:Entity {owner_id: $owner_id, project_id:$project_id}) 
                DETACH DELETE n
            """, owner_id=owner_id, project_id=project_id)
            
            # Ensure entity vector index exists without destroying it on every run
            session.run("""
                CREATE VECTOR INDEX entity_embedding_index IF NOT EXISTS
                FOR (e:Entity)
                ON (e.embedding)
                OPTIONS {indexConfig: {
                    `vector.dimensions`: 2048,
                    `vector.similarity_function`: 'cosine'
                }}
            """)
        driver.close()
        
        # 4. Parse and embed AST chunks
        print(f"DEBUG: Passing {len(absolute_file_list)} absolute file paths into parser...")
        result = parser.run_parsing_pipeline(absolute_file_list, owner_id, project_id)
        print(f"DEBUG: Parsing process completed. Results generated: {result}")
        
        processed_count = result.get("processed", 0)
        error_count = result.get("errors", 0)

        ingestion_status = {
            "status": "completed" if processed_count > 0 else "failed",
            "url": url,
            "processed_files": processed_count,
            "errors": error_count,
            "error_message": None if processed_count > 0 else "No compatible source files could be parsed."
        }
    except Exception as e:
        print(f"ERROR: Exception caught in background thread: {str(e)}")
        ingestion_status = {
            "status": "failed",
            "url": url,
            "processed_files": 0,
            "errors": 1,
            "error_message": str(e)
        }
    finally:
        # 5. Clean disk memory safely
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, onerror=ingest.force_remove_readonly)
            print(f"DEBUG: Wiped temp file directory execution branch at: {temp_dir}")

@app.post("/api/ingest")
async def start_ingestion(request: RepoRequest, background_tasks: BackgroundTasks):
    global ingestion_status
    if ingestion_status["status"] == "processing":
        raise HTTPException(status_code=400, detail="Ingestion is already in progress.")
        
    background_tasks.add_task(
        run_background_pipeline, 
        request.url, 
        request.owner_id, 
        request.project_id
    )
    return {"message": "Ingestion pipeline initiated", "status": "processing"}

@app.get("/api/ingest/status")
async def get_ingestion_status():
    return ingestion_status

# --- Context Querying Endpoint ---

@app.post("/api/query")
async def query_knowledge_graph(request: QueryRequest):
    try:
        response = nvidia_client.embeddings.create(
            input=request.question,
            model=config.NVIDIA_EMBEDDING_MODEL,
            extra_body={"input_type": "query"}
        )
        question_vector = response.data[0].embedding
    except Exception as e:
        async def error_stream():
            yield json.dumps({"response": f"Failed to generate embedding vector: {str(e)}"}) + "\n"
        return StreamingResponse(error_stream(), media_type="application/x-ndjson")

    try:
        cypher_query = query_engine.generate_cypher(
            request.question, 
            request.owner_id, 
            request.project_id
        )
    except Exception as e:
        async def cypher_error_stream():
            yield json.dumps({"response": f"Failed to generate Cypher query: {str(e)}"}) + "\n"
        return StreamingResponse(cypher_error_stream(), media_type="application/x-ndjson")

    context = ""
    try:
        driver = GraphDatabase.driver(config.URI, auth=(config.USER, config.PASSWORD))
        with driver.session() as session:
            result = session.run(cypher_query, question_vector=question_vector)
            records = list(result)
            if records:
                context = "\n".join([str(dict(record)) for record in records])
            else:
                context = "No direct knowledge graph matches found."
        driver.close()
    except Exception as e:
        context = f"Error executing Cypher query in Neo4j: {str(e)}"

    prompt = f"""
    You are an expert GraphRAG AI code assistant. Answer the user's question based on the retrieved code structure context from the Neo4j knowledge graph.
    
    Retrieved Context:
    {context}
    
    User Question: {request.question}
    Project Scope: {request.project_id}
    
    Provide a concise, helpful answer. If there is code, present it in clean markdown code blocks.
    """

    async def stream_generator():
        try:
            stream = nvidia_client.chat.completions.create(
                model=config.NVIDIA_CHAT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                stream=True
            )
            
            for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    word_chunk = {"chunk": chunk.choices[0].delta.content}
                    yield json.dumps(word_chunk) + "\n"
                    
        except Exception as e:
            print(f"DEBUG: Nvidia Stream Error: {str(e)}")
            yield json.dumps({"response": f"\n\nFailed to stream response: {str(e)}"}) + "\n"

    return StreamingResponse(stream_generator(), media_type="application/x-ndjson")

# --- Code Dependency Analysis Endpoints ---

@app.get("/api/callers/{function_name}")
async def get_who_calls_this(function_name: str, project_id: str, owner_id: str = "rohith_gurram"):
    query = """
    MATCH (caller:Entity {owner_id: $owner_id, project_id:$project_id})
          -[:CALLS]->
          (callee:Entity {name: $func_name, owner_id: $owner_id, project_id:$project_id})
    RETURN caller.name AS caller
    """
    try:
        driver = GraphDatabase.driver(config.URI, auth=(config.USER, config.PASSWORD))
        with driver.session() as session:
            result = session.run(query, owner_id=owner_id, project_id=project_id, func_name=function_name)
            callers = [record["caller"] for record in result]
        driver.close()
        return {"function": function_name, "project_id": project_id, "callers": callers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection error: {str(e)}")

@app.get("/api/callees/{function_name}")
async def get_what_this_calls(function_name: str, project_id: str, owner_id: str = "rohith_gurram"):
    query = """
    MATCH (caller:Entity {name: $func_name, owner_id: $owner_id, project_id:$project_id})
          -[:CALLS]->
          (callee:Entity {owner_id: $owner_id, project_id:$project_id})
    RETURN callee.name AS callee
    """
    try:
        driver = GraphDatabase.driver(config.URI, auth=(config.USER, config.PASSWORD))
        with driver.session() as session:
            result = session.run(query, owner_id=owner_id, project_id=project_id, func_name=function_name)
            callees = [record["callee"] for record in result]
        driver.close()
        return {"function": function_name, "project_id": project_id, "callees": callees}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection error: {str(e)}")

@app.get("/api/health")
async def health_check():
    return {"status": "online"}