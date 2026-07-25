#project 
## The problem
Getting comprehensive information on political figures and movements in the US is difficult. I'd like to make it easier to get answers to questions surrounding our politics.

## The goal
To map Politicians, Bills, Committees, Donors, and News Articles into a graph that can be queried to understand the relations between any of those similar to how statmuse allows someone to ask questions about a sport.

## Architecture
### Knowledge-Graph Creation
1. Create the ontology
2. Generate a knowledge graph off that ontology
3. Denoise the graph and dynamically serve information from it

#### Ontology
[[California Politics Knowledge Graph Ontology]]
##### initial work
labels:
`Organization` - `incorporation_date`, `hq_city`, `industrial_sector`, `tax_status`
- `:PAC`
- `:IndependentExpenditureCommittee`
- `:Corporation`
- `:LaborUnion`
- `:TradeAssociation`
- `:NonProfit`
- `:AdvocacyGroup`
- `:GrassrootsMovement`
- `:TribalNation`
- `:GovernmentAgency`
- `:MediaOrganization`
`Campaign` - `election_cycle`, `outcome`, `fppc_id`, `status`
- `CandidateCampaign`
- `BallotMeasureCampaign`
`PublicTenure`
`Bill`
`District`
`LegislativeEvent` - `type`, `date`
- `:Vote`
- `:Amendment`
- `:Hearing`
- `:Suspense`?
`NewsArticle`
`Chunks`
`PolicyArea`

relationships:
`SERVES_ON`
`CHAIRS`
`VICE_CHAIRS`
`ENDORSED`
`PUBLICLY_STATED`
`ASSOCIATED_WITH`
`REFERRED_TO`
`VOTED_ON`
`SPONSORED`
`INTERFERED_WITH`
`LOBBIED_FOR`
`LOBBIED_AGAINST`
`REPORTED_ON`
`DEPLOYED`
`FUNDED`
`SUPPORTED`
`TARGETED`
`REPORTED_ON`
`DECLARED_STANCE`
`CAMPAIGN_FOR`
`DENOUNCED`
`HELD_TENURE`

###### Questions
Political parties as organizations or as independent structures?
##### Prompt
I need help developing an ontology for a project with the description:

Project Overview: CA Political Influence GraphRAG Engine

An enterprise-grade, event-driven data pipeline and AI agentic architecture that ingests unstructured local news, campaign finance data, and legislative records to map networks of political influence in California into a Neo4j graph database.

  

This ontology will be used to define the entities, entity types/labels, relationships, and properties that will exist in my graph.

  

Currently, I have for entity types:

Politician, Campaign, CampaignActions, NewsArticle, Organization, Bill, Committee, Prop.

  

Relationships:

SERVES_ON

ENDORSED

PUBLICLY_STATED

ASSOCIATED_WITH

REFERRED_TO

VOTED_ON

SPONSORED

INTERFERED_WITH

LOBBIED_FOR

LOBBIED_AGAINST

REPORTED_ON

DEPLOYED

FUNDED

SUPPORTED

TARGETED

REPORTED_ON

### Event-Driven Asynchronous Ingestion Pipeline
A typical pipeline is essentially three stages:
- catching events and writing raw json to a stream
- ingesting and transforming that stream to structured json
- iterating on the structured json to place into a structured db with acid transactions

With gen AI since each interaction with an agent can take significant time, we need to prevent thread locking by triggering events every time we trigger an agent, and when the agent finishes its work.

![[California Politics Ingestion Pipeline]]


A possible path for data in this project is:
1. A document is uploaded or retrieved triggering an event.
2. A document processing worker retrieves the document.
3. Text is extracted from the document, stored in a structured form, and an event is triggered.
4. An embedding worker grabs the structured data.
5. An embedding is created, temporarily stored, and an event is triggered.
6. A vector DB worker indexes the embedding and text.

### GraphRAG
#### Indexing
- Text index - B-tree or !(full text index)
- Vector Index - vector embeddings
- !Structural index
#### Retrieval
- Node/Entity-Centric Retrieval - standard RAG embedding similarity
- Edge-Centric Retrieval - who-did-what-to-whom
- Neighborhood Retrieval - !(multi-hop contexts)
- Community Retrieval - clusters or thematic subgraphs via !(modularity) or !(PageRank)

#### !Reranking
- Cross-Encoder Rerankers
- Graph-Aware Reranking
- Embedding Fusion

#### sources
https://medium.com/@yu-joshua/graphrag-is-a-data-engineering-challenge-not-just-an-llm-trick-112079748e30
### Evals
#### Manual Dataset
This dataset will be composed of self produced examples of data derived from various different information sources that I am 100% confident in. That way, I can test the automated system for the insights that it draws and ensure that it is doing what I expect of it for a subset.

#### AI Evaluation
Additionally, I should have a more powerful model check the outcomes of a larger set of data to ensure that there is additional validation through the greater capabilities of a frontier model as well as utilizing the strength of the models to double check work better than they can produce it.

#### Process
I should be able to put articles through the agent extraction pipeline but have it return the relevant nodes rather than saving them to a db. Additionally, all these checks should be done with proper CI/CD pipeline.

### Context Engineering
~~With raw JSON I'll likely have a orchestration agent that controllers two subagents. One of which will attempt to generate the proper SQL to add to the DB while the other will check that the SQL is valid. This also means the orchestrator will have to handle error states.~~

I need agents to:
- Extract information from the raw JSON
- queries the db, understands the context in which the new information will be placed then generates the sql to transact
- check that the generated sql is valid
- orchestrate these parts, return the correct spot when finding errors

### LLMOps
I should be able to deal with rate limits and if my agents are struggling to produce the intended effect, I should fallback to a more powerful model.
Additionally, I should measure how well the models do at adhering to the schema by capturing error logs and properly route errors to be retried

###### sources
https://medium.com/@shreesonavane97/event-driven-genai-pipelines-designing-asynchronous-ai-systems-at-scale-21a61fa13fbc
### Testing
I should be testing on actual data rather than mock for things like db insertions

## Issues
[[California Politics Knowledge Graph Steps to attempt.]]

## Data Sources
###### campaign finance
https://calaccess.californiacivicdata.org/documentation/

###### legislation
https://docs.openstates.org/api-v3/

##### news
sf gate
calmatters
politico


## Tech Stack
Pydantic
OpenTelemetry - a data plane meaning it produces data about software processes that can be consumed by control plane


## Things I learned
Event-Driven Asynchronous Ingestion Pipeline
	If something isn't even driven, what is it driven by?
[[Index-Free Adjacency]]
[[ontology (information science)]]
	how is an ontology different from knowledge organization?
	Knowledge organization are methods meant to organize rich sources of information in relation to one another. This is opposed to ontology, which is meant to derive information from those rich sources and organize them into categories and relations.
Text index - B-tree or ([[full-text index]])
Vector Index - vector embeddings
Structural index - the way in which relationships between nodes/entries are defined
Node/Entity-Centric Retrieval - standard RAG embedding similarity
Edge-Centric Retrieval - who-did-what-to-whom
Neighborhood Retrieval - !(multi-hop contexts) / uses ANN like [HNSW](hierarchical%20navigable%20small%20world)
Community Retrieval - clusters or thematic subgraphs via !(modularity) or !(PageRank)
-
Cross-Encoder Rerankers
Graph-Aware Reranking
Embedding Fusion
MCP
[[Damerau-Levenshtein distance]]

## Future considerations
district overlap during redistricting