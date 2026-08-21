"""Seed knowledge base data including diagnostic and assessment questions."""
import sys
sys.path.insert(0, '.')
sys.path.insert(0, '.pylibs')

import json
from pathlib import Path

from app.db.database import get_session_factory
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.models.schemas import DiagnosticQuestion, SkillNode

def main():
    session_factory = get_session_factory()
    catalog = KnowledgeCatalogRepository(session_factory)
    
    # Find all knowledge base directories (project root is 1 level up from backend)
    backend_dir = Path(__file__).resolve().parent
    project_root = backend_dir.parent
    kb_root = project_root / "knowledge_base"
    if not kb_root.exists():
        print(f"Knowledge base directory not found: {kb_root}")
        return
    
    for kb_dir in sorted(kb_root.iterdir()):
        if not kb_dir.is_dir():
            continue
        
        metadata_path = kb_dir / "metadata.json"
        if not metadata_path.exists():
            continue
        
        with metadata_path.open("r", encoding="utf-8") as f:
            metadata = json.load(f)
        
        kb_id = metadata.get("knowledge_base_id", kb_dir.name)
        print(f"\nProcessing knowledge base: {kb_id}")
        
        # Step 1: Upsert knowledge base
        manifest = {
            "knowledge_base_id": kb_id,
            "name": metadata.get("name", kb_id),
            "version": metadata.get("version", "1.0"),
            "domain": metadata.get("domain"),
            "description": metadata.get("description", ""),
            "learner_levels": metadata.get("learner_levels", []),
            "raw_metadata": metadata,
        }
        catalog.upsert_knowledge_base(manifest)
        print(f"  Upserted knowledge base: {kb_id}")
        
        # Step 2: Upsert skill nodes
        skill_nodes = metadata.get("skill_nodes", [])
        if skill_nodes:
            nodes = []
            for node in skill_nodes:
                if isinstance(node, dict):
                    nodes.append(SkillNode(
                        node_id=node.get("node_id", node.get("name", "")),
                        knowledge_base_id=kb_id,
                        name=node.get("name", ""),
                        description=node.get("description", ""),
                        level=node.get("level"),
                        prerequisites=node.get("prerequisites", []),
                        knowledge_points=node.get("knowledge_points", []),
                        assessment_methods=node.get("assessment_methods", []),
                        metadata=node.get("metadata", {}),
                    ))
                elif isinstance(node, str):
                    nodes.append(SkillNode(
                        node_id=node,
                        knowledge_base_id=kb_id,
                        name=node,
                    ))
            catalog.upsert_skill_nodes(nodes, kb_id)
            print(f"  Upserted {len(nodes)} skill nodes")
        else:
            print(f"  No skill nodes defined")
        
        # Step 3: Upsert diagnostic questions
        diag_path = kb_dir / "diagnostic_questions.json"
        if diag_path.exists():
            with diag_path.open("r", encoding="utf-8") as f:
                questions_data = json.load(f)
            
            questions = [DiagnosticQuestion(**q) for q in questions_data]
            catalog.upsert_diagnostic_questions(questions)
            print(f"  Upserted {len(questions)} diagnostic questions")
        else:
            print(f"  No diagnostic_questions.json found")
        
        # Step 4: Upsert assessment questions
        assess_path = kb_dir / "assessment_questions.json"
        if assess_path.exists():
            with assess_path.open("r", encoding="utf-8") as f:
                questions_data = json.load(f)
            
            questions = [DiagnosticQuestion(**q) for q in questions_data]
            catalog.upsert_assessment_questions(questions)
            print(f"  Upserted {len(questions)} assessment questions")
        else:
            print(f"  No assessment_questions.json found")
    
    print("\nDone!")

if __name__ == "__main__":
    main()
