"""
Skill vocabulary + deterministic skill extraction.

Skills are recognised against a fixed, reviewed vocabulary instead of by an
LLM, so extraction is reproducible, cheap and cannot invent a skill that is
not literally in the text. Each entry is ``canonical name → (category,
aliases)``. Aliases are matched on word boundaries; aliases written in
``CASE:`` form are matched case-sensitively (``Go``, ``React``, ``Excel`` —
words that are also ordinary English).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

# category → {canonical: [aliases]}
_VOCAB: dict[str, dict[str, list[str]]] = {
    "language": {
        "Python": ["python"],
        "Java": ["java"],
        "JavaScript": ["javascript", "ecmascript", "CASE:JS"],
        "TypeScript": ["typescript", "CASE:TS"],
        "Go": ["golang", "CASE:Go"],
        "Rust": ["CASE:Rust"],
        "C": ["CASE:C"],
        "C++": ["c++", "cpp"],
        "C#": ["c#", "csharp"],
        "Ruby": ["CASE:Ruby"],
        "PHP": ["php"],
        "Kotlin": ["kotlin"],
        "Swift": ["CASE:Swift"],
        "Objective-C": ["objective-c", "objective c"],
        "Scala": ["scala"],
        "R": ["CASE:R", "r programming", "rstudio"],
        "SQL": ["sql"],
        "Bash": ["bash", "shell scripting"],
        "PowerShell": ["powershell"],
        "MATLAB": ["matlab"],
        "Dart": ["CASE:Dart"],
        "Elixir": ["elixir"],
        "Haskell": ["haskell"],
        "Perl": ["CASE:Perl"],
        "Lua": ["CASE:Lua"],
        "Solidity": ["solidity"],
        "Verilog": ["verilog", "systemverilog"],
        "VHDL": ["vhdl"],
        "HTML": ["html", "html5"],
        "CSS": ["css", "css3"],
    },
    "frontend": {
        "React": ["CASE:React", "react.js", "reactjs"],
        "React Native": ["react native"],
        "Next.js": ["next.js", "nextjs"],
        "Vue": ["vue", "vue.js", "vuejs"],
        "Angular": ["CASE:Angular", "angularjs"],
        "Svelte": ["svelte", "sveltekit"],
        "Redux": ["redux"],
        "Tailwind CSS": ["tailwind", "tailwindcss"],
        "Sass": ["CASE:Sass", "scss"],
        "jQuery": ["jquery"],
        "Webpack": ["webpack"],
        "Vite": ["CASE:Vite"],
        "Three.js": ["three.js", "threejs"],
        "Accessibility": ["accessibility", "wcag", "a11y"],
    },
    "backend": {
        "Node.js": ["node.js", "nodejs", "CASE:Node"],
        "Express": ["express.js", "expressjs", "CASE:Express"],
        "Django": ["django"],
        "Flask": ["CASE:Flask"],
        "FastAPI": ["fastapi"],
        "Spring": ["CASE:Spring", "spring framework"],
        "Spring Boot": ["spring boot"],
        "Ruby on Rails": ["ruby on rails", "CASE:Rails"],
        "Laravel": ["laravel"],
        ".NET": [".net", "dotnet", ".net core"],
        "ASP.NET": ["asp.net"],
        "GraphQL": ["graphql"],
        "REST APIs": ["rest api", "rest apis", "restful", "CASE:REST"],
        "gRPC": ["grpc"],
        "Microservices": ["microservices", "microservice architecture"],
        "Hibernate": ["hibernate"],
    },
    "data": {
        "PostgreSQL": ["postgresql", "postgres"],
        "MySQL": ["mysql"],
        "SQLite": ["sqlite"],
        "SQL Server": ["sql server", "mssql"],
        "Oracle Database": ["oracle database", "oracle db", "pl/sql"],
        "MongoDB": ["mongodb", "mongo"],
        "Redis": ["redis"],
        "Cassandra": ["cassandra"],
        "DynamoDB": ["dynamodb"],
        "Elasticsearch": ["elasticsearch", "opensearch"],
        "Neo4j": ["neo4j"],
        "Kafka": ["kafka"],
        "RabbitMQ": ["rabbitmq"],
        "Spark": ["apache spark", "pyspark", "CASE:Spark"],
        "Hadoop": ["hadoop"],
        "Airflow": ["airflow"],
        "dbt": ["CASE:dbt"],
        "Snowflake": ["snowflake"],
        "BigQuery": ["bigquery"],
        "Redshift": ["redshift"],
        "Databricks": ["databricks"],
        "ETL": ["etl", "elt", "data pipelines", "data pipeline"],
        "Data Modeling": ["data modeling", "data modelling"],
        "Data Analysis": ["data analysis", "data analytics"],
        "Pandas": ["pandas"],
        "NumPy": ["numpy"],
        "Tableau": ["tableau"],
        "Power BI": ["power bi", "powerbi"],
        "Looker": ["CASE:Looker"],
        "Excel": ["CASE:Excel", "microsoft excel"],
        "Statistics": ["statistics", "statistical analysis"],
        "A/B Testing": ["a/b testing", "ab testing", "experimentation"],
    },
    "ml": {
        "Machine Learning": ["machine learning", "CASE:ML"],
        "Deep Learning": ["deep learning"],
        "PyTorch": ["pytorch"],
        "TensorFlow": ["tensorflow"],
        "Keras": ["keras"],
        "scikit-learn": ["scikit-learn", "sklearn"],
        "NLP": ["nlp", "natural language processing"],
        "Computer Vision": ["computer vision", "opencv"],
        "LLMs": ["llm", "llms", "large language models", "large language model"],
        "RAG": ["CASE:RAG", "retrieval-augmented generation", "retrieval augmented generation"],
        "LangChain": ["langchain"],
        "Hugging Face": ["hugging face", "huggingface"],
        "MLOps": ["mlops"],
        "MLflow": ["mlflow"],
        "SageMaker": ["sagemaker"],
        "Vertex AI": ["vertex ai"],
        "CUDA": ["CASE:CUDA"],
        "Recommender Systems": ["recommender systems", "recommendation systems"],
    },
    "cloud_devops": {
        "AWS": ["aws", "amazon web services"],
        "GCP": ["gcp", "google cloud", "google cloud platform"],
        "Azure": ["azure", "microsoft azure"],
        "Docker": ["docker", "containers", "containerization"],
        "Kubernetes": ["kubernetes", "k8s"],
        "Terraform": ["terraform"],
        "Ansible": ["ansible"],
        "CI/CD": ["ci/cd", "continuous integration", "continuous delivery", "continuous deployment"],
        "Jenkins": ["jenkins"],
        "GitHub Actions": ["github actions"],
        "GitLab CI": ["gitlab ci"],
        "Git": ["CASE:Git", "github", "gitlab", "version control"],
        "Linux": ["linux", "unix"],
        "Nginx": ["nginx"],
        "Prometheus": ["prometheus"],
        "Grafana": ["grafana"],
        "Datadog": ["datadog"],
        "Serverless": ["serverless", "aws lambda", "cloud functions"],
        "CloudFormation": ["cloudformation"],
        "Helm": ["CASE:Helm"],
        "Observability": ["observability", "monitoring", "opentelemetry"],
        "SRE": ["CASE:SRE", "site reliability"],
    },
    "security": {
        "Application Security": ["application security", "appsec", "owasp"],
        "Penetration Testing": ["penetration testing", "pentesting", "pen testing"],
        "IAM": ["CASE:IAM", "identity and access management"],
        "OAuth": ["oauth", "openid connect", "oidc"],
        "SIEM": ["siem"],
        "Network Security": ["network security", "firewalls"],
        "Cryptography": ["cryptography", "encryption"],
    },
    "testing": {
        "Unit Testing": ["unit testing", "unit tests"],
        "TDD": ["CASE:TDD", "test-driven development"],
        "Selenium": ["selenium"],
        "Cypress": ["cypress"],
        "Playwright": ["playwright"],
        "Jest": ["CASE:Jest"],
        "pytest": ["pytest"],
        "JUnit": ["junit"],
        "QA": ["CASE:QA", "quality assurance"],
    },
    "mobile": {
        "Android": ["android"],
        "iOS": ["CASE:iOS"],
        "Flutter": ["flutter"],
        "SwiftUI": ["swiftui"],
        "Jetpack Compose": ["jetpack compose"],
    },
    "engineering": {
        "System Design": ["system design", "systems design"],
        "Distributed Systems": ["distributed systems"],
        "Data Structures": ["data structures"],
        "Algorithms": ["algorithms"],
        "API Design": ["api design"],
        "Embedded Systems": ["embedded systems", "embedded software", "firmware"],
        "RTOS": ["rtos"],
        "FPGA": ["fpga"],
        "Networking": ["networking", "tcp/ip"],
        "Performance Optimization": ["performance optimization", "performance tuning"],
        "Unity": ["CASE:Unity", "unity3d"],
        "Unreal Engine": ["unreal engine"],
        "Blockchain": ["blockchain", "web3", "smart contracts"],
    },
    "design": {
        "Figma": ["figma"],
        "Sketch": ["CASE:Sketch"],
        "Adobe XD": ["adobe xd"],
        "Photoshop": ["photoshop"],
        "Illustrator": ["CASE:Illustrator"],
        "UX Research": ["ux research", "user research", "usability testing"],
        "UI Design": ["ui design", "interface design", "visual design"],
        "Prototyping": ["prototyping", "wireframing", "wireframes"],
        "Design Systems": ["design systems", "design system"],
    },
    "product_business": {
        "Product Management": ["product management"],
        "Product Strategy": ["product strategy", "product roadmap", "roadmapping"],
        "Agile": ["agile"],
        "Scrum": ["scrum"],
        "Kanban": ["kanban"],
        "Jira": ["jira"],
        "Project Management": ["project management", "program management"],
        "Stakeholder Management": ["stakeholder management", "stakeholders"],
        "SEO": ["CASE:SEO", "search engine optimization"],
        "Google Analytics": ["google analytics"],
        "Content Marketing": ["content marketing", "copywriting"],
        "Salesforce": ["salesforce"],
        "HubSpot": ["hubspot"],
        "CRM": ["CASE:CRM"],
        "Financial Modeling": ["financial modeling", "financial modelling"],
        "Accounting": ["accounting", "bookkeeping"],
        "SAP": ["CASE:SAP"],
        "Six Sigma": ["six sigma"],
        "Customer Success": ["customer success"],
        "Sales": ["CASE:Sales", "business development"],
        "Mixpanel": ["mixpanel"],
        "Amplitude": ["CASE:Amplitude"],
    },
    "soft": {
        "Communication": ["communication skills", "written communication", "verbal communication"],
        "Leadership": ["leadership", "team lead", "led a team"],
        "Mentoring": ["mentoring", "mentorship", "coaching"],
        "Collaboration": ["cross-functional", "collaboration", "collaborative"],
        "Problem Solving": ["problem solving", "problem-solving"],
    },
}


@dataclass(frozen=True)
class SkillDef:
    name: str
    category: str


@dataclass(frozen=True)
class SkillHit:
    name: str
    category: str
    evidence: str  # the line of text the skill was found in


def _alias_pattern(alias: str) -> tuple[re.Pattern[str], bool]:
    case_sensitive = alias.startswith("CASE:")
    term = alias[5:] if case_sensitive else alias
    escaped = re.escape(term)
    # Word-ish boundaries that also work for terms like "c++", ".net", "c#".
    pattern = rf"(?<![A-Za-z0-9_+#./-]){escaped}(?![A-Za-z0-9_+#]|\.[A-Za-z0-9])"
    if term == "C":
        # A bare capital C only counts in list-like contexts ("C, C++", "in C.")
        pattern = r"(?<![A-Za-z0-9_+#./&-])C(?=\s*[,;/)]|\s+(?:and|or)\s|\s*$|\.\s)(?!\+\+|#)"
    if term == "R":
        pattern = r"(?<![A-Za-z0-9_+#./&-])R(?=\s*[,;/)]|\s+(?:and|or)\s|\s*$)(?![&+])"
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(pattern, flags), case_sensitive


@lru_cache(maxsize=1)
def _compiled() -> list[tuple[SkillDef, list[re.Pattern[str]]]]:
    out: list[tuple[SkillDef, list[re.Pattern[str]]]] = []
    for category, entries in _VOCAB.items():
        for name, aliases in entries.items():
            pats = [_alias_pattern(a)[0] for a in aliases]
            out.append((SkillDef(name=name, category=category), pats))
    return out


def all_skill_names() -> list[str]:
    return [d.name for d, _ in _compiled()]


def skill_category(name: str) -> str | None:
    for d, _ in _compiled():
        if d.name.lower() == name.lower():
            return d.category
    return None


def canonicalize(name: str) -> str | None:
    """Map free text ('postgres', 'K8s') to the canonical skill name, if known."""
    text = name.strip()
    if not text:
        return None
    for d, pats in _compiled():
        if d.name.lower() == text.lower():
            return d.name
        for p in pats:
            m = p.fullmatch(text) or (p.search(text) if len(text) <= 40 else None)
            if m and m.group(0).strip().lower() == text.lower():
                return d.name
    return None


def find_skills(text: str) -> list[SkillHit]:
    """All vocabulary skills that literally occur in ``text`` (first evidence line each)."""
    if not text:
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    hits: list[SkillHit] = []
    for d, pats in _compiled():
        for line in lines:
            if any(p.search(line) for p in pats):
                hits.append(SkillHit(name=d.name, category=d.category, evidence=line[:300]))
                break
    return hits


def mentions(text: str, skill_name: str) -> bool:
    """Does ``text`` mention this canonical skill (by any alias)?"""
    for d, pats in _compiled():
        if d.name == skill_name:
            return any(p.search(text) for p in pats)
    return False
