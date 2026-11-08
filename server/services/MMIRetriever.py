import os
import logging
from typing import List, Tuple, Dict, Any, Optional
from pinecone import Pinecone, ServerlessSpec
from dotenv import load_dotenv
from langchain.schema import Document

load_dotenv()

# Logger setup
logger = logging.getLogger(__name__)


def validate_scale_completeness(docs: List[Document]) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Validates that a collection of MMI reference documents represents every level (I to X)
    exactly once with non-empty content.

    Returns:
        (is_complete, message, details_dict)
    """
    expected_levels = set(range(1, 11))
    seen_levels = set()
    duplicate_levels = set()
    empty_levels = set()

    for doc in docs:
        meta = doc.metadata or {}
        level = meta.get("level")
        doc_id = meta.get("id", "")
        if level is None and "-" in doc_id:
            try:
                level = int(doc_id.split("-")[-1])
            except ValueError:
                level = None

        if level is not None and 1 <= level <= 10:
            if level in seen_levels:
                duplicate_levels.add(level)
            seen_levels.add(level)
            if not doc.page_content or not doc.page_content.strip():
                empty_levels.add(level)
        else:
            # Document missing a recognized MMI 1-10 level tag
            pass

    missing_levels = sorted(list(expected_levels - seen_levels))
    duplicates = sorted(list(duplicate_levels))
    empties = sorted(list(empty_levels))

    is_complete = (len(seen_levels) == 10 and not duplicates and not empties and len(docs) == 10)

    details = {
        "expected_count": 10,
        "actual_count": len(docs),
        "levels_present": sorted(list(seen_levels)),
        "missing_levels": missing_levels,
        "duplicate_levels": duplicates,
        "empty_levels": empties,
        "is_complete": is_complete,
    }

    if is_complete:
        return True, "Full MMI reference scale (I-X) is complete and verified.", details
    else:
        issues = []
        if missing_levels:
            issues.append(f"missing levels {missing_levels}")
        if duplicates:
            issues.append(f"duplicate levels {duplicates}")
        if empties:
            issues.append(f"empty definitions for levels {empties}")
        if len(docs) != 10:
            issues.append(f"expected 10 documents but got {len(docs)}")
        msg = f"Incomplete MMI reference scale: {'; '.join(issues)}."
        return False, msg, details


class MMIRetriever:
    """
    Retrieves MMI scale definitions from knowledge base using Pinecone Serverless.
    
    Supports two scientifically distinct reference retrieval modes:
      1. 'full_scale' (Default & Recommended): Deterministically fetches all 10 standard
         MMI definitions (I to X) in read-only mode, without arbitrary vector-ranking exclusions.
      2. 'vector_search': Uses Pinecone Serverless Integrated Embeddings (llama-text-embed-v2,
         1024 dimensions) to retrieve top-k candidate definitions by semantic similarity.
    """
    def __init__(self):
        self.EMBEDDING_MODEL_NAME = "llama-text-embed-v2"
        self.DIMENSIONALITY = 1024
        self.spec = ServerlessSpec(cloud="aws", region="us-east-1")
        self.index_name = "mmi-idx"
        self.last_retrieval_status = "UNINITIALIZED"
        self.last_retrieval_mode = "full_scale"
        self.last_retrieval_error = None

        api_key = os.environ.get('PINECONE_API')
        if api_key:
            try:
                self.pc = Pinecone(api_key=api_key)
                self.index = self.pc.Index(self.index_name)
            except Exception as e:
                logger.warning(f"Pinecone client init notice: {e}")
                self.pc = None
                self.index = None
        else:
            self.pc = None
            self.index = None

    def retrieve_full_scale(self) -> List[Document]:
        """
        Deterministically fetches all 10 official MMI scale definitions (mmi-1 to mmi-10)
        from Pinecone in read-only mode without vector-ranking exclusions or index modification.
        
        Validates completeness: exactly 10 unique, non-empty levels (I to X).
        """
        if not self.index:
            logger.warning("Pinecone index not available for full-scale retrieval")
            self.last_retrieval_status = "UNAVAILABLE"
            return []

        ids = [f"mmi-{i}" for i in range(1, 11)]
        try:
            fetch_res = self.index.fetch(ids=ids)
            vectors_map = getattr(fetch_res, "vectors", {}) or (
                fetch_res.get("vectors", {}) if isinstance(fetch_res, dict) else {}
            )

            results: List[Document] = []
            for i in range(1, 11):
                key = f"mmi-{i}"
                vec = vectors_map.get(key)
                if vec:
                    meta = getattr(vec, "metadata", None) or (
                        vec.get("metadata", {}) if isinstance(vec, dict) else {}
                    )
                    text = meta.get("text", "") if isinstance(meta, dict) else ""
                    results.append(
                        Document(
                            page_content=text,
                            metadata={
                                "id": key,
                                "level": i,
                                "source": "pinecone_mmi_idx",
                                "is_authoritative_reference": True,
                                "reference_mode": "full_scale",
                            }
                        )
                    )

            is_complete, msg, details = validate_scale_completeness(results)
            if is_complete:
                self.last_retrieval_status = "SUCCESS"
                logger.info("Successfully fetched complete 10-level MMI reference scale from Pinecone.")
            else:
                self.last_retrieval_status = "INCOMPLETE"
                logger.warning(f"Full-scale retrieval validation failed: {msg}")

            return results

        except Exception as e:
            logger.warning(f"Pinecone full-scale fetch error: {e}")
            self.last_retrieval_status = "FAILED"
            self.last_retrieval_error = str(e)
            return []

    def retrieve_vector_search(self, query: str, top_k: int = 3) -> List[Document]:
        """
        Retrieves top-k MMI reference documents by semantic similarity using
        Pinecone Serverless search_records or inference embed (llama-text-embed-v2, 1024 dims).
        """
        if not query or not query.strip():
            logger.warning("Empty query passed to retrieve_vector_search")
            self.last_retrieval_status = "EMPTY"
            return []

        if not self.index:
            logger.warning("Pinecone index not available")
            self.last_retrieval_status = "UNAVAILABLE"
            return []

        results: List[Document] = []

        # Method 1: Pinecone Native Serverless Integrated Search (search_records)
        try:
            res = self.index.search_records(
                namespace="__default__",
                query={"top_k": top_k, "inputs": {"text": query}}
            )
            hits_container = getattr(res, "result", res)
            hits = getattr(hits_container, "hits", None) or (
                hits_container.get("hits", []) if isinstance(hits_container, dict) else []
            )
            for hit in hits:
                fields = getattr(hit, "fields", None) or (
                    hit.get("fields", {}) if isinstance(hit, dict) else {}
                )
                hit_id = getattr(hit, "id", None) or (
                    hit.get("id", "") if isinstance(hit, dict) else ""
                )
                hit_score = getattr(hit, "score", None) or (
                    hit.get("score", 0.0) if isinstance(hit, dict) else 0.0
                )
                text = fields.get("text") if isinstance(fields, dict) else None
                level = None
                if "-" in hit_id:
                    try:
                        level = int(hit_id.split("-")[-1])
                    except ValueError:
                        pass
                if text:
                    results.append(
                        Document(
                            page_content=text,
                            metadata={
                                "id": hit_id,
                                "level": level,
                                "score": float(hit_score),
                                "source": "pinecone_mmi_idx",
                                "is_authoritative_reference": True,
                                "reference_mode": "vector_search",
                            }
                        )
                    )

            if results:
                self.last_retrieval_status = "SUCCESS"
                return results
        except (AttributeError, TypeError, Exception) as e:
            logger.warning(f"Pinecone search_records notice: {e}. Attempting inference fallback.")

        # Method 2: Pinecone Native Inference Embed Fallback
        try:
            if self.pc and hasattr(self.pc, "inference"):
                emb = self.pc.inference.embed(
                    model="llama-text-embed-v2",
                    inputs=[query],
                    parameters={"input_type": "query", "dimension": 1024, "truncate": "END"}
                )
                vector = emb[0].values if hasattr(emb[0], "values") else emb[0].get("values", [])
                query_res = self.index.query(vector=vector, top_k=top_k, include_metadata=True)
                if hasattr(query_res, "matches") and query_res.matches is not None:
                    matches = query_res.matches
                elif isinstance(query_res, dict):
                    matches = query_res.get("matches", [])
                else:
                    matches = []
                for record in matches:
                    rec_meta = getattr(record, "metadata", None) or record.get("metadata", {}) or {}
                    rec_id = getattr(record, "id", None) or record.get("id", "")
                    rec_score = getattr(record, "score", None) or record.get("score", 0.0)
                    text = rec_meta.get("text") if isinstance(rec_meta, dict) else None
                    level = None
                    if "-" in rec_id:
                        try:
                            level = int(rec_id.split("-")[-1])
                        except ValueError:
                            pass
                    if text:
                        results.append(
                            Document(
                                page_content=text,
                                metadata={
                                    "id": rec_id,
                                    "level": level,
                                    "score": float(rec_score),
                                    "source": "pinecone_mmi_idx",
                                    "is_authoritative_reference": True,
                                    "reference_mode": "vector_search",
                                }
                            )
                        )

                if results:
                    self.last_retrieval_status = "SUCCESS"
                    return results
        except Exception as e:
            logger.warning(f"Pinecone inference embed notice: {e}")
            self.last_retrieval_error = str(e)

        self.last_retrieval_status = "FAILED" if not results else "SUCCESS"
        return results

    def retrieveDocs(self, query: str = "", reference_mode: Optional[str] = None) -> List[Document]:
        """
        Retrieves MMI reference documents using configured reference mode:
          - 'full_scale': (Default) Deterministically supplies all 10 MMI definitions.
          - 'vector_search': Retrieves top-k candidate definitions by semantic similarity.
        """
        mode = (reference_mode or os.environ.get("MMI_REFERENCE_MODE", "full_scale")).lower()
        self.last_retrieval_mode = mode

        if mode == "full_scale":
            return self.retrieve_full_scale()
        elif mode == "vector_search":
            return self.retrieve_vector_search(query=query)
        else:
            logger.warning(f"Unrecognized reference_mode '{mode}'; defaulting to 'full_scale'.")
            return self.retrieve_full_scale()

    def retrieve(self, query: str) -> list[int]:
        """Legacy helper returning numerical MMI scores."""
        if not query:
            logger.error("Empty Query")
            return []

        docs = self.retrieveDocs(query, reference_mode="vector_search")
        result = []
        for doc in docs:
            doc_id = doc.metadata.get("id", "")
            if "-" in doc_id:
                try:
                    result.append(int(doc_id.split("-")[-1]))
                except ValueError:
                    pass
        return result

