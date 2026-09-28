# Drop Rate Content Machine v1

## Purpose
Create an original, measurable daily content engine with minimal founder intervention.

## Operating loops

### 1. Daily trend radar
Permitted sources -> normalize -> dedupe -> evidence/fact check -> relevance score -> content signal.

Signal classes: new releases, meaningful price moves, verified rare sales, game/community trends, new Drop Rate inventory, grails and low stock.

### 2. Event-driven content
Backend emits content opportunities when trusted Drop Rate facts change. n8n consumes the event and calls backend/AI services; it does not invent canonical facts.

### 3. Inspiration library
Third-party creator/site content is reference material only unless licensed. Store source URL, pattern notes and rights status. Learn abstract features such as hook structure, pacing, format, topic and CTA. Do not reproduce scripts, media, distinctive creative expression or watermarks.

### 4. Generation
One factual brief -> platform-native variants for Instagram, Facebook, TikTok, YouTube and X. AI receives verified facts separately from creative instructions.

### 5. Validation and authority
Auto-publish LOW risk factual/evergreen content only after validation. Human review remains mandatory for uncertain facts, legal/safety issues, unverified sales/prices, giveaways/discount claims, accusations, leaked/unreleased material or rights ambiguity.

### 6. Measurement
Store external post ID plus impressions/views, watch time where available, engagement, profile/site clicks and attributable Shopify sessions/orders/revenue. Never optimize only for vanity engagement.

### 7. Learning
Rank content patterns using normalized performance by platform, format, audience size and post age. Feed winning abstract patterns into future briefs. Keep failed posts as negative examples. Fine-tuning is deferred until enough clean labelled outcomes exist.

## Automation contracts
- content.signal.detected.v1
- content.job.ready.v1
- content.publish.requested.v1
- content.published.v1
- content.metrics.refresh_requested.v1
- content.performance.observed.v1

All externally visible actions require an idempotency key. Retries must never duplicate a social post.

## Revenue objective
Primary business outcome: attributable gross profit / content effort and assisted conversion. Secondary: qualified sessions, conversion rate, email/owned-audience growth. Engagement metrics are diagnostic, not the goal.
