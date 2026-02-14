# DhyanApp Bot Agents - Documentation

Technical documentation for the DhyanApp bot engagement system.

## Documents

| Document | Description |
|----------|-------------|
| [System Architecture](./system-architecture.md) | High-level architecture, components, and data flow |
| [Post Creation Workflow](./post-creation-workflow.md) | How bot posts and quotes are generated and published |
| [Liking Workflow](./liking-workflow.md) | How bots like posts (both bot-generated and user posts) |
| [Commenting Workflow](./commenting-workflow.md) | How bots generate and post comments |
| [Bot Personas](./bot-personas.md) | Bot account configurations, personas, and rotation |
| [Firestore Schema](./firestore-schema.md) | Database collections, documents, and field definitions |

## Quick Reference

- **Post generation**: Local cron job -> Python script -> Firestore
- **Engagement (bot posts)**: Firestore trigger -> Cloud Functions -> Cloud Tasks -> likes/comments
- **Engagement (user posts)**: Local Python script (manual/cron) -> likes/comments
- **8 bot personas** rotating daily via round-robin
- **2 daily posts**: Quote at 6 AM IST, Content post at 6 PM IST
