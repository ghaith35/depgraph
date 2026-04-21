from __future__ import annotations
from pydantic import BaseModel
from typing import Optional


class Node(BaseModel):
    id: str
    label: str
    language: str
    size: int
    is_cycle: bool = False
    cluster: str
    parse_error: bool = False
    is_outlier_hub: bool = False


class Edge(BaseModel):
    source: str
    target: str
    type: str
    symbol: Optional[str] = None
    line: int
    is_cycle: bool = False
    has_dynamic_target: bool = False


class Graph(BaseModel):
    nodes: list[Node]
    edges: list[Edge]


class CycleReport(BaseModel):
    scc_count: int
    node_count_in_cycles: int
    edge_count_in_cycles: int
    sccs: list[list[str]]
    simple_cycles: list[list[str]]


class SetupSteps(BaseModel):
    runtime: str
    install_cmd: Optional[str] = None
    build_cmd: Optional[str] = None
    run_cmd: Optional[str] = None
    env_vars: list[str] = []
    notes: list[str] = []


class RepoStats(BaseModel):
    file_count: int
    total_size_bytes: int
    total_loc: int
    languages: dict[str, int]
    commit_sha: str
    repo_url: str
    analysis_duration_ms: int


class AnalysisResult(BaseModel):
    job_id: str
    stats: RepoStats
    graph: Graph
    cycles: CycleReport
    setup: SetupSteps
    unresolved_imports_count: int = 0
    schema_version: str = "1.0"
