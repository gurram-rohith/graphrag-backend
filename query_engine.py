from openai import OpenAI
import config

def generate_cypher(question: str, owner_id: str, project_id: str) -> str:
    """
    Uses an LLM to generate a Cypher query from a natural language question.
    Instructs the LLM to utilize Neo4j's Vector Search for semantic retrieval.
    """
    prompt = f"""
    You are an expert Neo4j Cypher developer.
    Your job is to translate the user's question into a SINGLE valid Cypher query.
    
    GRAPH SCHEMA:
    - Nodes: (File), (Function), (Entity)
    - Properties: name, summary, owner_id, project_id, summary_embedding
    - Relationships: (File)-[:CONTAINS]->(Function), (Function)-[:CALLS]->(Entity), (File)-[:CALLS]->(Entity)
    
    SEARCH STRATEGY:
    Use Neo4j Vector Index search to find conceptually similar nodes. The backend has already converted the user's question into a mathematical vector and will pass it as the `$question_vector` parameter.
    
    CHOOSE EXACTLY ONE OF THE FOLLOWING TEMPLATES BASED ON THE USER'S QUESTION:
    
    OPTION 1 (Basic Search - Use for general questions about what the project does):
    CALL db.index.vector.queryNodes('file_summary_index', 10, $question_vector)
    YIELD node, score
    WHERE node.owner_id = '{owner_id}' AND node.project_id = '{project_id}'
    RETURN labels(node)[0] AS Type, node.name AS Name, node.summary AS Summary, score
    ORDER BY score DESC
    
    OPTION 2 (Dependency Search - Use if user asks about dependencies, tech stack, or function calls):
    CALL db.index.vector.queryNodes('file_summary_index', 3, $question_vector)
    YIELD node, score
    WHERE node.owner_id = '{owner_id}' AND node.project_id = '{project_id}'
    MATCH (node)-[:CONTAINS|CALLS*1..2]-(related)
    RETURN labels(node)[0] AS Type, node.name AS Name, node.summary AS Summary, 
           collect(DISTINCT related.name) AS RelatedEntities, score
    ORDER BY score DESC
    
    User Question: {question}
    
    STRICT RULES:
    1. Return EXACTLY ONE raw Cypher query. NEVER output multiple queries.
    2. Do not include markdown formatting (like ```cypher).
    3. Do not include any explanations.
    4. ALWAYS use `$question_vector` as the parameter for the vector index.
    5. The vector index MUST ALWAYS `YIELD node, score`. NEVER yield anything else like `related`.
    """
    
    try:
        client = OpenAI(
            base_url="[https://integrate.api.nvidia.com/v1](https://integrate.api.nvidia.com/v1)",
            api_key=config.NVIDIA_API_KEY
        )
        
        completion = client.chat.completions.create(
            model=config.NVIDIA_CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        
        # Clean up the output to ensure it's just the raw query, removing markdown if the LLM hallucinated it
        raw_query = completion.choices[0].message.content.strip()
        if raw_query.startswith("```cypher"):
            raw_query = raw_query.replace("```cypher", "").replace("```", "").strip()
        elif raw_query.startswith("```"):
            raw_query = raw_query.replace("```", "").strip()
            
        return raw_query
        
    except Exception as e:
        print(f"Error generating Cypher query: {e}")
        # Fallback safe query if the API call completely fails
        return f"""
        CALL db.index.vector.queryNodes('file_summary_index', 5, $question_vector)
        YIELD node, score
        WHERE node.owner_id = '{owner_id}' AND node.project_id = '{project_id}'
        RETURN labels(node)[0] AS Type, node.name AS Name, node.summary AS Summary, score
        ORDER BY score DESC
        """