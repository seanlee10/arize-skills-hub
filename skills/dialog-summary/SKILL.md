# Dialogue Summary Skill

## Description

Use this skill when the user asks you to summarize a short dialogue, chat transcript, messenger conversation, or meeting-like exchange.

## Goal

Create a concise summary that captures only the main point of the conversation, including important decisions, requests, plans, or essential context, while omitting unnecessary details.

## Input

The input is usually a speaker-labeled dialogue. Each line may contain a speaker name followed by their message.

Example:

Alice: Are you coming to dinner tonight?  
Bob: I might be late because of work.  
Alice: That's okay. I'll save you some food.

## Procedure

1. Read the entire dialogue carefully before summarizing.
2. Identify the main participants and ensure their names are transcribed exactly as in the dialogue.
3. Identify the main topic or outcome of the conversation.
4. Extract only the most essential decisions, requests, plans, problems, or commitments that are central to the conversation.
5. Exclude greetings, small talk, filler expressions, repeated information, and any details that do not directly affect the main point or outcome.
6. Do not include minor actions, reactions, or emotional context unless they are critical to understanding the main point.
7. Avoid adding interpretations, assumptions, or inferred motivations that are not explicitly stated in the dialogue.
8. Write a concise summary in natural language, focusing strictly on what is directly supported by the dialogue and omitting any secondary or non-essential details.

## Output Format

Write only the final summary.

The summary should be 1–3 sentences.

## Rules

* Include only the main point(s) and essential details; omit minor or secondary information.
* Do not add information, interpretations, or motivations that are not explicitly stated in the dialogue.
* Do not confuse or alter the names of participants; use names exactly as given.
* Do not misattribute actions, intentions, or statements to the wrong speaker.
* Preserve important names, dates, times, places, and commitments as stated.
* Prefer a clear third-person summary.
* Do not quote the dialogue unless the exact wording is essential to the meaning.
* Be as concise as possible while including all key points.

## Quality Checklist

Before finalizing, check:

* Does the summary capture only the main point(s) and essential details, omitting minor or extraneous information?
* Are all names and attributions accurate and faithful to the dialogue?
* Are concrete plans, requests, or decisions included, and only if explicitly stated?
* Is irrelevant small talk, filler, or unnecessary detail removed?
* Is the summary free of added interpretations or assumptions?
* Is the summary concise and within 1–3 sentences?