## 1. Node Labels & Sub-Labels

### Informational & Context Layer

#### `:NewsArticle`

- `id`: `STRING` _(Primary Key: the article's canonical URL)_
    
- `title`: `STRING`
    
- `author`: `STRING` _(Byline as published; absent when the article carries none)_
    
- `publisher`: `STRING` _(e.g., "Los Angeles Times", "CalMatters")_
    
- `published_date`: `DATE`
    
- `summary`: `STRING` _(LLM-generated high-level tl;dr)_
    

#### `:Chunk`

- `id`: `STRING` _(Primary Key: `article_id` + "#chunk_" + `index`)_
    
- `text`: `STRING` _(The raw markdown text block passed to the LLM at query time)_
    
- `embedding`: `LIST<FLOAT>` _(Vector embedding array for semantic search)_
    
- `index`: `INTEGER` _(Sequential ordering within the article)_
    

#### `:PolicyArea`

- `id`: `STRING` _(Primary Key: Lowercase slug, e.g., "climate-change")_
    
- `name`: `STRING` _(e.g., "Climate Change & Environment")_
    
- `embedding`: `LIST<FLOAT>` _(Vector embedding of the topic name/description)_
    

### Government & Institutional Layer

#### `:Politician`

- `id`: `STRING`
    
- `first_name`: `STRING`
    
- `last_name`: `STRING`
    
- `birth_date`: `DATE`
    
- `current_party`: `STRING` _(e.g., "Democrat", "Republican")_
    

#### `:LegislativeTenure`

- `id`: `STRING` _(Primary Key: `politician_id` + "_" + `chamber` + "_" + `start_year`)_
    
- `chamber`: `STRING` _(e.g., "Assembly", "Senate")_
    
- `start_year`: `INTEGER`
    
- `end_year`: `INTEGER`
    
- `party_affiliation`: `STRING` _(Captures the party they ran under for this specific slice of time)_
    

#### `:District`

- `id`: `STRING` _(Primary Key: `chamber` + "_" + `district_number` + "_" + `cycle_year`)_
    
- `number`: `INTEGER`
    
- `cycle_year`: `INTEGER` _(e.g., 2020)_
    

#### `:RedistrictingCycle`

- `id`: `STRING` _(Primary Key: Year of line drawing, e.g., "2021")_
    
- `year`: `INTEGER`
    
- `mid_cycle`: `BOOL`
#### `:Committee`

- `id`: `STRING` _(Primary Key: State ledger committee code)_
    
- `name`: `STRING` _(e.g., "Assembly Appropriations Committee")_
    
- `chamber`: `STRING` _(e.g., "Assembly", "Senate", "Joint")_
    

#### `:Bill`

- `id`: `STRING` _(Primary Key: Session ID + Bill Number, e.g., "20252026_SB32")_
    
- `number`: `STRING` _(e.g., "SB-32")_
    
- `session`: `STRING` _(e.g., "2025-2026")_
    
- `current_status`: `STRING` _(e.g., "Chaptered", "Died in Committee")_
    

#### `:LegislativeEvent`

- _Note: This node always carries `:LegislativeEvent` plus one of the following sub-labels:_
    
    - `:Vote`
        
    - `:Amendment`
        
    - `:Hearing`
        
- `id`: `STRING` _(Primary Key: Ledger tracking ID or hash of Event + Date)_
    
- `type`: `STRING` _(e.g., "Committee Vote", "Gut and Amend", "Public Testimony")_
    
- `date`: `DATE`
    
- `description`: `STRING` _(Brief summary of the action taken)_
    

#### `:Prop`

- `id`: `STRING` _(Primary Key: Election Date + Prop Number, e.g., "202611_Prop5")_
    
- `number`: `STRING` _(e.g., "Prop 5")_
    
- `election_date`: `DATE`
    
- `official_title`: `STRING`
    
- `summary`: `STRING` _(The official Attorney General summary)_
    

### Influence, Funding, & Campaign Layer

#### `:Campaign`

- _Note: This node always carries `:Campaign` plus one of the following sub-labels:_
    
    - `:CandidateCampaign`
        
    - `:BallotMeasureCampaign`
        
- `id`: `STRING`
    
- `name`: `STRING` _(Official committee name, e.g., "Working Californians Against Prop X")_
    
- `election_cycle`: `INTEGER` _(e.g., 2026)_
    
- `status`: `STRING` _(e.g., "Active", "Terminated")_
    

#### `:Organization`

- _Note: This node always carries `:Organization` plus one or more specific structural sub-labels:_
    
    - `:PAC` | `:IE_Committee` | `:Corporation` | `:LaborUnion` | `:TradeAssociation` | `:NonProfit` | `:AdvocacyGroup` | `:GrassrootsMovement` | `:TribalNation` | `:GovernmentAgency` | `:MediaOrganization`
        
- `id`: `STRING`
    
- `name`: `STRING`
    
- `industry_sector`: `STRING` _(e.g., "Oil & Gas", "Tech", "Labor - Education")_
    
- `fppc_id`: `STRING` _(Optional: Used if they are a formally registered lobbyist employer)_

#### `:ExternalIdentifier`
    
- `scheme`: `STRING` _(e.g., "openstates-person", "california-legislature-person", "california-fppc-committee", "california-business-registry")_
    
- `value`: `STRING` _(e.g., "AB999", "SB555", "CA-90210")_
    
- `source`: `STRING` _(e.g., "OpenStates", "California Legislature", "FPPC", "California Secretary of State")_
    
- `source_url`: `STRING` _(e.g., "https://openstates.org/person/CA/", "https://www.legislature.ca.gov/", "https://www.fppc.ca.gov/", "https://www.sos.ca.gov/")_
    
- `verified_at`: `DATETIME` _(e.g., "2026-01-01T00:00:00")_
    
- `status`: `STRING` _(e.g., "ACTIVE", "DEPRECATED", "UNVERIFIED")_
    

## 2. Relationships & Properties

| **Source Node**                  | **Relationship Type** | **Target Node**          | **Properties**                                                                          | **Description**                                                |
| -------------------------------- | --------------------- | ------------------------ | --------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `:Politician`                    | `HELD_TENURE`         | `:LegislativeTenure`     | _None_                                                                                  | Links a person to a specific term in office.                   |
| `:LegislativeTenure`             | `REPRESENTS_DISTRICT` | `:District`              | _None_                                                                                  | Connects a specific term to its matching cycle district.       |
| `:District`                      | `TRANSITIONED_BY`     | `:RedistrictingCycle`    | _None_                                                                                  | Points an old-cycle district to the redistricting event.       |
| `:RedistrictingCycle`            | `EVOLVED_INTO`        | `:District`              | *None*                                                                                  | Connects the cycle to the newly spawned districts.             |
| `:LegislativeTenure`             | `SERVES_ON`           | `:Committee`             | _None_                                                                                  | Standard legislative committee assignment.                     |
| `:LegislativeTenure`             | `CHAIRS`              | `:Committee`             | _None_                                                                                  | Identifies the committee chair for high-influence routing.     |
| `:LegislativeTenure`             | `VICE_CHAIRS`         | `:Committee`             | _None_                                                                                  | Identifies the committee vice chair.                           |
| `:LegislativeTenure`             | `VOTED_AYE`           | `:LegislativeEvent`      | `sequence_number: INT`                                                                  | Links a tenure to an affirmative vote event.                   |
| `:LegislativeTenure`             | `VOTED_NO`            | `:LegislativeEvent`      | `sequence_number: INT`                                                                  | Links a tenure to a negative vote event.                       |
| `:LegislativeTenure`             | `ABSTAINED`           | `:LegislativeEvent`      | `sequence_number: INT`                                                                  | Links a tenure to an abstention or unrecorded vote.            |
| `:LegislativeEvent`              | `ACTION_ON`           | `:Bill`                  | _None_                                                                                  | Connects the distinct timeline events back to the parent bill. |
| `:Bill`                          | `ABOUT_TOPIC`         | `:PolicyArea`            | _None_                                                                                  | Maps a bill to its thematic category hub.                      |
| `:Prop`                          | `ABOUT_TOPIC`         | `:PolicyArea`            | _None_                                                                                  | Maps a proposition to its thematic category hub.               |
| `:Campaign`                      | `CAMPAIGN_FOR`        | `:Prop` \| `:Politician` | _None_                                                                                  | Denotes the target of a temporary committee's mission.         |
| `:Organization`                  | `FUNDED`              | `:Campaign`              | `amount: FLOAT`<br><br>  <br><br>`date: DATE`<br><br>  <br><br>`transaction_id: STRING` | Tracking explicit FPPC-disclosed financial transfers.          |
| `:Organization`                  | `LOBBIED_FOR`         | `:Bill`                  | *None*                                                                                  | Tracking recorded support on official lobbying reports.        |
| `:Organization`                  | `LOBBIED_AGAINST`     | `:Bill`                  | *None*                                                                                  | Tracking recorded opposition on official lobbying reports.     |
| `:Politician` \| `:Organization` | `ENDORSED`            | `:Prop` \| `:Campaign`   | _None_                                                                                  | Captures binary, official public backing.                      |
| `:Politician` \| `:Organization` | `DENOUNCED`           | `:Prop` \| `:Campaign`   | _None_                                                                                  | Captures official public condemnation.                         |
| `:Politician` \| `:Organization` | `DECLARED_STANCE`     | `:Prop` \| `:Bill`       | `alignment: STRING`<br><br>  <br><br>_(Values: "POSITIVE", "NEGATIVE", "NEUTRAL")_      | Used for nuanced public comments caught in news articles.      |
| `:NewsArticle`                   | `HAS_CHUNK`           | `:Chunk`                 | _None_                                                                                  | Parent-to-child composition for RAG slicing.                   |
| _Any Core Entity_                | `MENTIONED_IN`        | `:Chunk`                 | _None_                                                                                  | Hard edge created when an entity is extracted from that chunk. |
| `:NewsArticle` \| `:Chunk`       | `DISCUSSES_TOPIC`     | `:PolicyArea`            | _None_                                                                                  | Direct thematic edge for generalized policy news articles.     |
| _Any resolvable core entity_     | `HAS_IDENTIFIER`      | `:ExternalIdentifier`    | _None_                                                                                  | Connects an internal entity to an identifier assigned by an external authority. |