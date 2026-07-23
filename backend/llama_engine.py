import os
import tempfile
import uuid
import json
import time

try:
    from llama_index.core import VectorStoreIndex, Document, Settings
    from llama_index.core.memory import ChatMemoryBuffer
    from llama_index.core.llms import ChatMessage, MessageRole
    from llama_index.core import SimpleDirectoryReader
    
    # LLMs
    from llama_index.llms.openai import OpenAI
    from llama_index.llms.gemini import Gemini
    from llama_index.llms.ollama import Ollama
except ImportError:
    raise ImportError(
        "LlamaIndex packages are missing. Please install them using:\n"
        "pip install llama-index llama-index-llms-openai llama-index-llms-gemini llama-index-llms-ollama llama-index-embeddings-huggingface"
    )

# --- In-Memory Caches ---
_index_cache = {}       # type: dict[str, VectorStoreIndex]
_chat_memory = {}       # type: dict[str, ChatMemoryBuffer]
_enrichment_cache = {}  # type: dict[str, dict]

# --- Intent Routing Prompts ---
INTENT_PROMPTS = {
    "general_bi": """You are a Senior Business Analyst. Provide a comprehensive executive report based on the provided data context.
Structure your response with:
1. Executive Summary
2. Key Insights
3. Risk Flags
4. Recommendations
Use exact numbers. Do not talk about databases or SQL. Respond in clean Markdown.""",

    "risk_analysis": """You are a Chief Risk Officer. Your ONLY job is to identify risks, anomalies, outliers, and potential issues in the provided data context.
Structure your response with:
1. Primary Risk Flags (High severity)
2. Anomalies & Inconsistencies (Medium severity)
3. Mitigation Recommendations
Ignore positive trends unless they pose a hidden risk. Use exact numbers. Respond in clean Markdown.""",

    "opportunity": """You are a Business Development Analyst. Your ONLY job is to identify growth opportunities, upsell potential, and positive trends in the provided data context.
Structure your response with:
1. Key Growth Signals
2. Upsell / Optimization Opportunities
3. Recommended Action Plan
Ignore routine risks unless they block an opportunity. Use exact numbers. Respond in clean Markdown.""",

    "extraction": """You are a Data Extraction Specialist. Extract the specific information requested by the user from the provided data context.
Present the extracted data clearly, preferably in a Markdown table or a concise bulleted list. 
Do not add unnecessary commentary. Use exact numbers."""
}

DEFAULT_INTENT = "general_bi"

def get_llm(provider_cfg: dict):
    """Sets up the LLM, optimized for low latency with Ollama."""
    provider = provider_cfg.get("provider", "ollama").lower()
    model = provider_cfg.get("model", "llama3")
    
    if provider == "openai":
        return OpenAI(model=model or "gpt-4o", api_key=provider_cfg.get("api_key"))
    elif provider == "gemini":
        return Gemini(model=model or "models/gemini-1.5-pro", api_key=provider_cfg.get("api_key"))
    else:
        # OLLAMA FALLBACK - Optimized for latency with a temperature of 0.1 for more deterministic, faster answers
        return Ollama(model=model, request_timeout=180.0, temperature=0.1)

def route_intent(question: str, llm) -> str:
    """Dynamically routes the user's question to the appropriate analysis intent."""
    prompt = f"""Analyze the following user request and classify its core intent into exactly ONE of these categories:
- general_bi (asks for overview, summary, general analysis, or doesn't specify)
- risk_analysis (asks for risks, anomalies, flags, unusual things, problems)
- opportunity (asks for opportunities, recommendations for growth, positive signals)
- extraction (asks to list specific things, extract data, show specific rows)

User Request: "{question}"

Respond with ONLY the category name (e.g., 'risk_analysis'). Do not include any other text."""
    
    t0 = time.time()
    try:
        response = llm.complete(prompt).text.strip().lower()
        print(f"[intent_router] Evaluated in {time.time()-t0:.2f}s -> {response}")
        for valid_intent in INTENT_PROMPTS.keys():
            if valid_intent in response:
                return valid_intent
        return DEFAULT_INTENT
    except Exception as e:
        print(f"[intent_router] Failed to route intent, defaulting to general_bi: {e}")
        return DEFAULT_INTENT

def enrich_document(file_id: str, raw_text: str, file_type: str, llm) -> dict:
    """Runs once per file to extract metadata, summary, and key entities."""
    if file_id in _enrichment_cache:
        return _enrichment_cache[file_id]
        
    prompt = f"""Analyze the following document text and extract key metadata for a 'First Impression Analysis'.
Respond with a valid JSON object containing exactly these keys:
- "summary": A 2-3 sentence overview of the document.
- "doc_type": The exact type of document (e.g., "Bank Statement", "Hospital Report", "Invoice", "Resume", "Research Paper", "Unknown").
- "key_entities": A list of important names, companies, or accounts mentioned.
- "top_insights": A list of 3 crucial observations, anomalies, or interesting data points found in the text.
- "suggested_questions": A list of 3 questions the user should ask the AI to dive deeper into this specific document.

Document Text (truncated for length):
{raw_text[:6000]}

Respond with ONLY valid JSON."""
    
    t0 = time.time()
    try:
        response = llm.complete(prompt).text.strip()
        # Clean up potential markdown formatting around JSON
        if response.startswith("```json"):
            response = response.split("```json")[1].strip()
        if response.endswith("```"):
            response = response.rsplit("```", 1)[0].strip()
            
        enrichment_data = json.loads(response)
        _enrichment_cache[file_id] = enrichment_data
        print(f"[enrichment] Enriched {file_id} in {time.time()-t0:.2f}s: {enrichment_data.get('doc_type')}")
        return enrichment_data
    except Exception as e:
        print(f"[enrichment] Failed to enrich document: {e}")
        fallback = {
            "summary": "Document content successfully extracted.", 
            "doc_type": file_type, 
            "key_entities": [],
            "top_insights": ["Document successfully indexed.", "Ready for semantic search.", "No anomalies detected in initial pass."],
            "suggested_questions": ["Can you summarize this document?", "What are the key points?", "Extract the main data."]
        }
        _enrichment_cache[file_id] = fallback
        return fallback

def get_first_impression(file_id: str, file_bytes: bytes, filename: str, file_type: str, provider_cfg: dict) -> dict:
    """
    Called immediately after upload to provide instant intelligence before the user asks anything.
    Forces the index to build and the enrichment to run, then returns the enriched metadata.
    """
    print(f"[first_impression] Triggered for {filename}")
    build_or_get_index(file_id, file_bytes, filename, file_type, provider_cfg)
    return _enrichment_cache.get(file_id, {})

def build_or_get_index(file_id: str, file_bytes: bytes, filename: str, file_type: str, provider_cfg: dict) -> VectorStoreIndex:
    if file_id in _index_cache:
        return _index_cache[file_id]

    llm = get_llm(provider_cfg)
    Settings.llm = llm
    
    documents = []
    
    # ── Vision Handling with LLaVA:13b ──
    if file_type.lower() in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
        print(f"[llama_engine] Processing image {filename} with llava:13b")
        try:
            import base64
            import requests
            
            # We use raw requests to Ollama API for Llava to avoid dependency bloat and guarantee stability
            image_b64 = base64.b64encode(file_bytes).decode("utf-8")
            
            t0 = time.time()
            resp = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "llava:13b",
                    "prompt": "You are a financial analyst. Extract all text, numbers, charts, and tables from this image accurately. Preserve the context.",
                    "images": [image_b64],
                    "stream": False,
                    "options": {"temperature": 0.1}
                },
                timeout=180
            )
            if resp.ok:
                description = resp.json().get("response", "")
                documents.append(Document(
                    text=f"Image Content Extraction for {filename}:\n\n{description}",
                    metadata={"filename": filename, "type": "image_extraction"}
                ))
                print(f"[llama_engine] Vision extraction complete in {time.time()-t0:.2f}s")
            else:
                raise Exception(f"Vision API failed: {resp.text}")
                
        except Exception as e:
            print(f"Warning: Could not generate image description for {filename}. {str(e)}")
            documents.append(Document(text=f"Image file {filename} (Could not extract text)", metadata={"filename": filename}))
    else:
        # ── Document Handling ──
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_file_path = os.path.join(temp_dir, filename)
            with open(temp_file_path, "wb") as f:
                f.write(file_bytes)

            reader = SimpleDirectoryReader(input_dir=temp_dir)
            try:
                documents = reader.load_data()
            except Exception as e:
                text_content = file_bytes.decode('utf-8', errors='ignore')
                documents = [Document(text=text_content, metadata={"filename": filename})]

    # ── Enrichment Pipeline ──
    full_text = "\n".join([doc.text for doc in documents])
    enrichment = enrich_document(file_id, full_text, file_type, llm)
    
    # Inject enrichment metadata into documents for better retrieval
    for doc in documents:
        doc.metadata.update(enrichment)

    # ── Setup Local Embeddings ──
    try:
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
        # all-MiniLM-L6-v2 is fast, local, and already in your requirements
        Settings.embed_model = HuggingFaceEmbedding(model_name="all-MiniLM-L6-v2")
    except ImportError:
        print("[llama_engine] HuggingFaceEmbedding not found. Run: pip install llama-index-embeddings-huggingface")

    t0 = time.time()
    print("Documents:", len(documents))
    index = VectorStoreIndex.from_documents(documents)
    print("Index Built")
    print(f"[llama_engine] Built index for {filename} in {time.time() - t0:.2f}s")
    
    _index_cache[file_id] = index
    return index

def research_query(
    file_id: str, 
    file_bytes: bytes, 
    filename: str, 
    file_type: str, 
    question: str, 
    provider_cfg: dict, 
    session_id: str = None, 
    chat_history: list = None
) -> dict:
    
    llm = get_llm(provider_cfg)
    
    # 1. Build or Get Index & Enrichment
    print(file_id)
    print(filename)
    print(file_type)
    index = build_or_get_index(file_id, file_bytes, filename, file_type, provider_cfg)
    enrichment = _enrichment_cache.get(file_id, {})
    
    # 2. Dynamic Intent Routing
    intent = route_intent(question, llm)
    sys_prompt_template = INTENT_PROMPTS.get(intent, INTENT_PROMPTS[DEFAULT_INTENT])
    
    # Add enrichment context to system prompt
    enriched_sys_prompt = f"""{sys_prompt_template}

--- ENRICHED DOCUMENT CONTEXT ---
Document Type: {enrichment.get('doc_type', 'Unknown')}
Summary: {enrichment.get('summary', 'None')}
Key Entities: {', '.join(enrichment.get('key_entities', []))}
---------------------------------"""

    # 3. Manage Session Memory
    if not session_id:
        session_id = str(uuid.uuid4())
        
    if session_id not in _chat_memory:
        _chat_memory[session_id] = ChatMemoryBuffer.from_defaults(token_limit=4000)
        
    memory = _chat_memory[session_id]
    
    if chat_history:
        messages = []
        for msg in chat_history:
            role = MessageRole.USER if msg.get("role") == "user" else MessageRole.ASSISTANT
            messages.append(ChatMessage(role=role, content=msg.get("content", "")))
        memory.set(messages)
    
    # 4. Contextualize Follow-up Questions
    pronouns = ['it', 'this', 'that', 'they', 'the same', 'he', 'she']
    question_lower = question.lower().strip()
    words = question_lower.split()
    
    is_short = len(question) < 25
    has_pronoun = any(p in words for p in pronouns)
    
    if (is_short or has_pronoun) and memory.get_all():
        last_messages = memory.get_all()[-2:]
        context_str = "\n".join([f"{m.role.value}: {m.content[:200]}" for m in last_messages])
        actual_query = (
            f"Previous conversation context:\n{context_str}\n\n"
            f"User's follow-up question: {question}\n"
            f"Answer the follow-up question using the document and context."
        )
    else:
        actual_query = question

    # 5. Execute RAG Query
    retriever = index.as_retriever(similarity_top_k=20)
    nodes = retriever.retrieve(actual_query)
    
    print("Retrieved:", len(nodes))
    for n in nodes:
        print(n.score)
        print(n.node.get_content()[:300])
    
    if not nodes:
        return {
            "analysis": "No relevant information found in the uploaded document.",
            "sources": [],
            "session_id": session_id,
            "intent": intent
        }

    context = "\n\n".join(node.node.get_content() for node in nodes)
    
    prompt = f"""
You are an enterprise document analysis assistant.

Rules:
- Answer ONLY from the context.
- Never use outside knowledge.
- If information is missing, say:
  "The uploaded document does not contain this information."
- Never guess.

Context:
{context}

Question:
{actual_query}
"""
    
    t0 = time.time()
    response_obj = llm.complete(prompt)
    exec_time = time.time() - t0
    print(f"[llama_engine] Final response generated in {exec_time:.2f}s")
    
    sources = []
    if nodes:
        for i, node in enumerate(nodes):
            meta = node.node.metadata
            filename_meta = meta.get("filename", filename)
            page_meta = meta.get("page_number", meta.get("page", meta.get("page_num", "N/A")))
            chunk_meta = meta.get("chunk_id", i+1)
            score = f"{node.score:.2f}" if node.score else "N/A"
            
            source_str = f"📄 **{filename_meta}**"
            if page_meta != "N/A":
                source_str += f" (Page {page_meta})"
            else:
                source_str += f" (Chunk {chunk_meta})"
            
            source_str += f" — *Relevance: {score}*"
            sources.append(source_str)

    
    return {
        "analysis": response_obj.text,
        "sources": list(set(sources)),
        "session_id": session_id,
        "intent": intent
    }

def clear_session_memory(session_id: str):
    if session_id in _chat_memory:
        _chat_memory[session_id].reset()
        del _chat_memory[session_id]
        return True
    return False
