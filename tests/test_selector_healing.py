import pytest
import sqlite3
import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from bs4 import BeautifulSoup
from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from knowledge_map.adapters.sqlite_db import (
    init_db,
    register_publication,
    cache_scraped_html,
    get_publication,
    has_unresolved_selector_proposal,
    set_publication_healing_in_progress,
    insert_selector_proposal,
    get_latest_selector_proposal,
)
from knowledge_map.core.healing import (
    preprocess_html,
    run_selector_healing_flow,
    get_generator_agent,
    get_critic_agent,
    ArticleSelectors,
    CriticFeedback,
    annotate_ground_truth
)
from knowledge_map.schemas import DeploymentKind, ModelDeployment
from knowledge_map.utils.models import get_chat_model


def test_explicit_selector_healing_agents_share_deployment(monkeypatch):
    deployment = ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model="explicit-selector-healing-model",
        endpoint="http://selector-healing.test:9999",
    )
    monkeypatch.setenv("LLAMA_CPP_MODEL", "ambient-local-model")

    with patch(
        "knowledge_map.core.healing.get_chat_model",
        wraps=get_chat_model,
    ) as factory:
        generator = get_generator_agent(deployment=deployment, defer_check=True)
        critic = get_critic_agent(deployment=deployment, defer_check=True)

    assert [call.args[0] for call in factory.call_args_list] == [
        deployment,
        deployment,
    ]
    assert generator.model is critic.model
    assert generator.model.model_name == deployment.model


@pytest.mark.anyio
async def test_selector_healing_flow_binds_one_deployment_and_stores_proposal(tmp_path):
    db_path = str(tmp_path / "test_explicit_deployment.db")
    init_db(db_path)
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    cache_scraped_html(
        "https://testpub.com/art1",
        "testpub",
        """
        <html>
        <body>
            <h1 class="entry-title">Expected Headline</h1>
            <span class="author">By John Doe</span>
            <div class="content">This is a long article content with multiple stopwords so it validates cleanly.</div>
        </body>
        </html>
        """,
        validation="VALIDATION_FAILED",
        db_path=db_path,
    )
    deployment = ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model="explicit-selector-healing-model",
        endpoint="http://selector-healing.test:9999",
    )

    generator_result = MagicMock()
    generator_result.output = ArticleSelectors(
        title="h1.entry-title",
        author="span.author",
        date="",
        body="div.content",
    )
    generator_result.all_messages.return_value = []
    critic_result = MagicMock()
    critic_result.output = CriticFeedback(is_valid=True, issues=[])
    generator = MagicMock()
    async def mock_generator_run(*args, **kwargs):
        return generator_result
    generator.run = mock_generator_run
    critic = MagicMock()
    async def mock_critic_run(*args, **kwargs):
        return critic_result
    critic.run = mock_critic_run

    with patch(
        "knowledge_map.core.healing.get_generator_agent",
        return_value=generator,
    ) as generator_factory, patch(
        "knowledge_map.core.healing.get_critic_agent",
        return_value=critic,
    ) as critic_factory:
        await run_selector_healing_flow(
            publication_id="testpub",
            tripping_article_url="https://testpub.com/art1",
            db_path=db_path,
            bypass_guards=True,
            deployment=deployment,
        )

    generator_factory.assert_called_once_with(deployment)
    critic_factory.assert_called_once_with(deployment)

    proposal = get_latest_selector_proposal("testpub", db_path=db_path)
    assert proposal["status"] == "PENDING_REVIEW"
    assert json.loads(proposal["selectors_json"]) == {
        "title": "h1.entry-title",
        "author": "span.author",
        "date": "",
        "body": "div.content",
    }

def test_preprocess_html_with_article():
    raw_html = """
    <html>
    <head>
        <title>Article Title</title>
        <style>body { color: red; }</style>
        <script>console.log("hello");</script>
    </head>
    <body class="main-body" id="page-body" data-tracking="123" style="margin: 0;">
        <nav class="main-nav">Navigation</nav>
        <article class="article-content" id="art-id" data-extra="remove-me">
            <h1 class="entry-title" id="art-title" data-large-attr="large-value-that-we-strip">Actual Title</h1>
            <span class="author" itemprop="author">By Author Name</span>
            <time class="date" datetime="2026-07-07">July 7, 2026</time>
            <svg>svg block</svg>
            <noscript>noscript block</noscript>
            <iframe src="ad.html"></iframe>
            <img src="img.jpg" />
            <div class="content-body">
                <p>First paragraph of the article.</p>
                <p>Second paragraph of the article.</p>
            </div>
        </article>
        <footer class="footer">Footer content</footer>
    </body>
    </html>
    """
    
    cleaned = preprocess_html(raw_html)
    soup = BeautifulSoup(cleaned, "html.parser")
    
    # Verify the article exists and its key attributes are cleaned but class/id are preserved
    article = soup.find("article")
    assert article is not None
    assert article.get("class") == ["article-content"]
    assert article.get("id") == "art-id"
    assert "data-extra" not in article.attrs
    
    # Verify heavy stripped tags inside/outside
    assert soup.find("head") is None
    assert soup.find("script") is None
    assert soup.find("style") is None
    assert soup.find("svg") is None
    assert soup.find("iframe") is None
    assert soup.find("img") is None
    
    # Verify layout & structural elements are stripped again
    assert soup.find("footer") is None
    assert soup.find("nav") is None
    assert soup.find("noscript") is None
    
    # Verify the body and its cleaned attributes
    body = soup.find("body")
    assert body is not None
    assert body.get("class") == ["main-body"]
    assert body.get("id") == "page-body"
    assert "data-tracking" not in body.attrs
    assert "style" not in body.attrs
    
    h1 = soup.find("h1")
    assert h1 is not None
    assert h1.get("class") == ["entry-title"]
    assert h1.get("id") == "art-title"
    assert "data-large-attr" not in h1.attrs

    # Verify semantic attributes (itemprop, datetime) are preserved
    author_span = soup.find("span", class_="author")
    assert author_span is not None
    assert author_span.get("itemprop") == "author"

    date_time = soup.find("time")
    assert date_time is not None
    assert date_time.get("datetime") == "2026-07-07"


def test_preprocess_html_fallback_no_article():
    raw_html = """
    <html>
    <head>
        <title>Article Title</title>
        <style>body { color: red; }</style>
        <script>console.log("hello");</script>
    </head>
    <body class="main-body" id="page-body" data-tracking="123" style="margin: 0;">
        <nav class="main-nav">Navigation</nav>
        <div class="article-content">
            <h1 class="entry-title" id="art-title" data-large-attr="large-value-that-we-strip">Actual Title</h1>
            <span class="author" itemprop="author">By Author Name</span>
            <time class="date" datetime="2026-07-07">July 7, 2026</time>
            <svg>svg block</svg>
            <noscript>noscript block</noscript>
            <iframe src="ad.html"></iframe>
            <img src="img.jpg" />
            <div class="content-body">
                <p>First paragraph of the article.</p>
                <p>Second paragraph of the article.</p>
            </div>
        </div>
        <footer class="footer">Footer content</footer>
    </body>
    </html>
    """
    
    cleaned = preprocess_html(raw_html)
    soup = BeautifulSoup(cleaned, "html.parser")
    
    # Verify stripped tags
    assert soup.find("head") is None
    assert soup.find("script") is None
    assert soup.find("style") is None
    assert soup.find("svg") is None
    assert soup.find("iframe") is None
    assert soup.find("img") is None
    
    # Verify layout & structural elements are stripped again
    assert soup.find("footer") is None
    assert soup.find("nav") is None
    assert soup.find("noscript") is None
    
    # Verify attributes: class and id are kept, others are stripped
    body = soup.find("body")
    assert body is not None
    assert body.get("class") == ["main-body"]
    assert body.get("id") == "page-body"
    assert "data-tracking" not in body.attrs
    assert "style" not in body.attrs
    
    h1 = soup.find("h1")
    assert h1 is not None
    assert h1.get("class") == ["entry-title"]
    assert h1.get("id") == "art-title"
    assert "data-large-attr" not in h1.attrs

    # Verify semantic attributes (itemprop, datetime) are preserved
    author_span = soup.find("span", class_="author")
    assert author_span is not None
    assert author_span.get("itemprop") == "author"

    date_time = soup.find("time")
    assert date_time is not None
    assert date_time.get("datetime") == "2026-07-07"



def test_init_db_resets_healing_in_progress(tmp_path):
    db_file = tmp_path / "test_init_db.db"
    db_path = str(db_file)
    
    init_db(db_path)
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    
    # Set healing_in_progress to True
    set_publication_healing_in_progress("testpub", True, db_path=db_path)
    pub_before = get_publication("testpub", db_path=db_path)
    assert pub_before["healing_in_progress"] is True
    
    # Re-run init_db (startup reset)
    init_db(db_path)
    pub_after = get_publication("testpub", db_path=db_path)
    assert pub_after["healing_in_progress"] is False


@pytest.mark.anyio
async def test_concurrency_guards_skip_healing(tmp_path):
    db_file = tmp_path / "test_concurrency.db"
    db_path = str(db_file)
    
    init_db(db_path)
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    cache_scraped_html("https://testpub.com/art1", "testpub", "<html></html>", validation="VALIDATION_FAILED", db_path=db_path)
    
    # Case 1: Unresolved proposal exists
    insert_selector_proposal(
        publication_id="testpub",
        selectors_json='{"title": "h1"}',
        trigger_article_url="https://testpub.com/art1",
        status="PENDING_REVIEW",
        critic_iterations=1,
        db_path=db_path
    )
    
    with patch("knowledge_map.core.healing.get_generator_agent") as mock_gen_agent:
        await run_selector_healing_flow("testpub", "https://testpub.com/art1", db_path=db_path)
        # Should skip and not even try to initialize agents
        mock_gen_agent.assert_not_called()
        
    # Clear unresolved proposal status to test healing_in_progress guard
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE selector_proposals SET status = 'APPROVED'")
    conn.commit()
    conn.close()
    
    # Case 2: healing_in_progress is True
    set_publication_healing_in_progress("testpub", True, db_path=db_path)
    
    with patch("knowledge_map.core.healing.get_generator_agent") as mock_gen_agent:
        await run_selector_healing_flow("testpub", "https://testpub.com/art1", db_path=db_path)
        # Should skip
        mock_gen_agent.assert_not_called()
        
    # Case 3: bypass_guards works even when guards are active
    generator_agent = MagicMock()
    mock_gen_result = MagicMock()
    mock_gen_result.output = ArticleSelectors(title="h1", author="span", date="time", body="div")
    mock_gen_result.all_messages = MagicMock(return_value=[])
    async def mock_gen_run(*args, **kwargs):
        return mock_gen_result
    generator_agent.run = mock_gen_run
    
    critic_agent = MagicMock()
    mock_crit_result = MagicMock()
    mock_crit_result.output = CriticFeedback(is_valid=True, issues=[])
    async def mock_crit_run(*args, **kwargs):
        return mock_crit_result
    critic_agent.run = mock_crit_run
    
    await run_selector_healing_flow(
        "testpub", 
        "https://testpub.com/art1", 
        db_path=db_path, 
        bypass_guards=True,
        generator_agent=generator_agent,
        critic_agent=critic_agent
    )
    # Since bypass_guards was True, it ran and completed.
    # Verify it saved a PENDING_REVIEW proposal
    assert has_unresolved_selector_proposal("testpub", db_path=db_path) is True


@pytest.mark.anyio
async def test_generator_critic_loop_immediate_success(tmp_path):
    db_file = tmp_path / "test_loop_success.db"
    db_path = str(db_file)
    
    init_db(db_path)
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    
    html = """
    <html>
    <body>
        <h1 class="entry-title">Expected Headline</h1>
        <span class="author">By John Doe</span>
        <div class="content">This is a long article content with multiple stopwords so it validates cleanly.</div>
    </body>
    </html>
    """
    cache_scraped_html("https://testpub.com/art1", "testpub", html, validation="VALIDATION_FAILED", db_path=db_path)
    
    # Mock LLM for Generator
    def mock_generator_model(messages, info):
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "title": "h1.entry-title",
                    "author": "span.author",
                    "date": "",
                    "body": "div.content"
                },
                tool_call_id="call_1"
            )
        ])
        
    # Mock LLM for Critic (success)
    def mock_critic_model(messages, info):
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "is_valid": True,
                    "issues": []
                },
                tool_call_id="call_2"
            )
        ])
        
    generator_agent = get_generator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    
    with generator_agent.override(model=FunctionModel(mock_generator_model)), \
         critic_agent.override(model=FunctionModel(mock_critic_model)):
         
        await run_selector_healing_flow(
            publication_id="testpub",
            tripping_article_url="https://testpub.com/art1",
            db_path=db_path,
            generator_agent=generator_agent,
            critic_agent=critic_agent
        )
        
    # Verify proposal was saved as PENDING_REVIEW
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM selector_proposals WHERE publication_id = 'testpub'")
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row["status"] == "PENDING_REVIEW"
    assert row["critic_iterations"] == 1
    assert row["trigger_article_url"] == "https://testpub.com/art1"
    
    selectors = json.loads(row["selectors_json"])
    assert selectors["title"] == "h1.entry-title"
    assert selectors["author"] == "span.author"
    assert selectors["body"] == "div.content"
    
    # Verify healing_in_progress is cleared
    pub = get_publication("testpub", db_path=db_path)
    assert pub["healing_in_progress"] is False


@pytest.mark.anyio
async def test_generator_critic_loop_retry_success(tmp_path):
    db_file = tmp_path / "test_loop_retry.db"
    db_path = str(db_file)
    
    init_db(db_path)
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    
    html = """
    <html>
    <body>
        <h1 class="entry-title">Expected Headline</h1>
        <span class="author">By John Doe</span>
        <div class="content">This is a long article content with multiple stopwords so it validates cleanly.</div>
    </body>
    </html>
    """
    cache_scraped_html("https://testpub.com/art1", "testpub", html, validation="VALIDATION_FAILED", db_path=db_path)
    
    generator_calls = 0
    def mock_generator_model(messages, info):
        nonlocal generator_calls
        generator_calls += 1
        tool_name = info.output_tools[0].name
        
        # Propose bad selector first time, good selector second time
        title_sel = "h1.wrong" if generator_calls == 1 else "h1.entry-title"
        
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "title": title_sel,
                    "author": "span.author",
                    "date": "",
                    "body": "div.content"
                },
                tool_call_id=f"call_{generator_calls}"
            )
        ])
        
    critic_calls = 0
    def mock_critic_model(messages, info):
        nonlocal critic_calls
        critic_calls += 1
        tool_name = info.output_tools[0].name
        
        # Reject first time, approve second time
        is_valid = False if critic_calls == 1 else True
        issues = ["Title was empty"] if critic_calls == 1 else []
        
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "is_valid": is_valid,
                    "issues": issues
                },
                tool_call_id=f"call_{critic_calls + 10}"
            )
        ])
        
    generator_agent = get_generator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    
    with generator_agent.override(model=FunctionModel(mock_generator_model)), \
         critic_agent.override(model=FunctionModel(mock_critic_model)):
         
        await run_selector_healing_flow(
            publication_id="testpub",
            tripping_article_url="https://testpub.com/art1",
            db_path=db_path,
            generator_agent=generator_agent,
            critic_agent=critic_agent
        )
        
    # Verify iteration count and approval
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM selector_proposals WHERE publication_id = 'testpub'")
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row["status"] == "PENDING_REVIEW"
    assert row["critic_iterations"] == 2
    
    selectors = json.loads(row["selectors_json"])
    assert selectors["title"] == "h1.entry-title"


@pytest.mark.anyio
async def test_generator_critic_loop_exhaustion(tmp_path):
    db_file = tmp_path / "test_loop_exhaustion.db"
    db_path = str(db_file)
    
    init_db(db_path)
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    cache_scraped_html("https://testpub.com/art1", "testpub", "<html></html>", validation="VALIDATION_FAILED", db_path=db_path)
    
    def mock_generator_model(messages, info):
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "title": "wrong-title",
                    "author": "wrong-author",
                    "date": "wrong-date",
                    "body": "wrong-body"
                },
                tool_call_id="call_gen"
            )
        ])
        
    def mock_critic_model(messages, info):
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "is_valid": False,
                    "issues": ["Always wrong"]
                },
                tool_call_id="call_crit"
            )
        ])
        
    generator_agent = get_generator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    
    with generator_agent.override(model=FunctionModel(mock_generator_model)), \
         critic_agent.override(model=FunctionModel(mock_critic_model)), \
         patch("knowledge_map.utils.console.ConsoleNotifier.notify_critical_failure") as mock_console:
         
        await run_selector_healing_flow(
            publication_id="testpub",
            tripping_article_url="https://testpub.com/art1",
            db_path=db_path,
            generator_agent=generator_agent,
            critic_agent=critic_agent
        )
        
        # Verify console alert was dispatched
        mock_console.assert_called_once()
        
    # Verify proposal status is HEALING_FAILED and iteration is 3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM selector_proposals WHERE publication_id = 'testpub'")
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row["status"] == "HEALING_FAILED"
    assert row["critic_iterations"] == 5
    
    # Verify healing_in_progress is cleared
    pub = get_publication("testpub", db_path=db_path)
    assert pub["healing_in_progress"] is False


@pytest.mark.anyio
async def test_generator_critic_loop_programmatic_lock_in(tmp_path):
    db_file = tmp_path / "test_lock_in.db"
    db_path = str(db_file)
    
    init_db(db_path)
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    
    html = """
    <html>
    <body>
        <h1 class="entry-title">Expected Headline</h1>
        <span class="author">By John Doe</span>
        <time class="pubdate" datetime="2026-07-06T12:00:00Z">July 6, 2026</time>
        <div class="content">This is a long article content with multiple stopwords so it validates cleanly.</div>
    </body>
    </html>
    """
    cache_scraped_html("https://testpub.com/art1", "testpub", html, validation="VALIDATION_FAILED", db_path=db_path)
    
    generator_calls = 0
    def mock_generator_model(messages, info):
        nonlocal generator_calls
        generator_calls += 1
        tool_name = info.output_tools[0].name
        
        if generator_calls == 1:
            # Iteration 1: correct metadata, wrong body
            args = {
                "title": "h1.entry-title",
                "author": "span.author",
                "date": "time.pubdate",
                "body": "div.wrong"
            }
        else:
            # Iteration 2: wrong metadata (simulating model regression), correct body
            args = {
                "title": "h1.wrong",
                "author": "span.wrong",
                "date": "time.wrong",
                "body": "div.content"
            }
            
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args=args,
                tool_call_id=f"call_{generator_calls}"
            )
        ])
        
    critic_calls = 0
    def mock_critic_model(messages, info):
        nonlocal critic_calls
        critic_calls += 1
        tool_name = info.output_tools[0].name
        
        # Reject first time due to body, approve second time
        is_valid = False if critic_calls == 1 else True
        issues = ["Body selector extracted nothing"] if critic_calls == 1 else []
        
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "is_valid": is_valid,
                    "issues": issues
                },
                tool_call_id=f"call_{critic_calls + 10}"
            )
        ])
        
    generator_agent = get_generator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    
    with generator_agent.override(model=FunctionModel(mock_generator_model)), \
         critic_agent.override(model=FunctionModel(mock_critic_model)):
         
        await run_selector_healing_flow(
            publication_id="testpub",
            tripping_article_url="https://testpub.com/art1",
            db_path=db_path,
            generator_agent=generator_agent,
            critic_agent=critic_agent
        )
        
    # Verify iteration count is 2 and final proposal contains the locked-in metadata selectors AND corrected body selector
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM selector_proposals WHERE publication_id = 'testpub'")
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row["status"] == "PENDING_REVIEW"
    assert row["critic_iterations"] == 2
    
    selectors = json.loads(row["selectors_json"])
    assert selectors["title"] == "h1.entry-title"
    assert selectors["author"] == "span.author"
    assert selectors["date"] == "time.pubdate"
    assert selectors["body"] == "div.content"


def test_annotate_ground_truth():
    # 1. Headline, Date (time tag with datetime), and Author
    html = """
    <div>
        <h1 class="title-class">The Silicon Valley Crisis</h1>
        <span class="byline">By John Doe</span>
        <time class="date-class" datetime="2026-07-06T12:00:00Z">July 6</time>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    gt = {
        "headline": "The Silicon Valley Crisis",
        "datePublished": "2026-07-06T12:00:00Z",
        "authors": ["John Doe"]
    }

    annotate_ground_truth(soup, gt)

    title_el = soup.find(attrs={"data-is-title-gt": "true"})
    assert title_el is not None
    assert title_el.name == "h1"
    assert title_el.get_text() == "The Silicon Valley Crisis"

    author_el = soup.find(attrs={"data-is-author-gt": "true"})
    assert author_el is not None
    assert author_el.name == "span"
    assert author_el.get_text() == "By John Doe"

    date_el = soup.find(attrs={"data-is-date-gt": "true"})
    assert date_el is not None
    assert date_el.name == "time"
    assert date_el["datetime"] == "2026-07-06T12:00:00Z"


def test_annotate_ground_truth_variants():
    # Test date in plain text format and multiple authors in a single tag
    html = """
    <div>
        <div class="article-title">Silicon Valley’s Crisis!</div>
        <div class="meta">Published: June 18, 2026</div>
        <div class="authors">By Jane Doe and John Smith</div>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    gt = {
        "headline": "Silicon Valley's Crisis",
        "datePublished": "2026-06-18T00:00:00Z",
        "authors": ["Jane Doe", "John Smith"]
    }

    annotate_ground_truth(soup, gt)

    title_el = soup.find(attrs={"data-is-title-gt": "true"})
    assert title_el is not None
    assert title_el.get_text() == "Silicon Valley’s Crisis!"

    date_el = soup.find(attrs={"data-is-date-gt": "true"})
    assert date_el is not None
    assert "June 18, 2026" in date_el.get_text()

    author_els = soup.find_all(attrs={"data-is-author-gt": "true"})
    assert len(author_els) > 0
    assert any("Jane Doe" in el.get_text() for el in author_els)


def test_annotate_ground_truth_nested_authors():
    # Test multiple authors in nested tags
    html = """
    <div class="authors">
        <span class="author-link">Jane Doe</span> and 
        <span class="author-link">John Smith</span>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    gt = {
        "headline": "Test Title",
        "datePublished": "2026-06-18T00:00:00Z",
        "authors": ["Jane Doe", "John Smith"]
    }
    annotate_ground_truth(soup, gt)

    # We should have annotated the two inner span tags, not the parent div
    author_spans = soup.find_all("span", attrs={"data-is-author-gt": "true"})
    assert len(author_spans) == 2
    texts = [span.get_text() for span in author_spans]
    assert "Jane Doe" in texts
    assert "John Smith" in texts

    parent_div = soup.find("div", class_="authors")
    assert not parent_div.has_attr("data-is-author-gt")
