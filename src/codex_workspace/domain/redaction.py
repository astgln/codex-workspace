"""Best-effort filtering of recognizable credentials, not a data-loss prevention system."""
import re


def public_text(text):
    text = re.sub(r'-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----[\s\S]*?(?:-----END (?:[A-Z0-9]+ )?PRIVATE KEY-----|\Z)', '[private key hidden]', text)
    text = re.sub(r'\b\d{6,15}:[A-Za-z0-9_-]{30,}\b', '[Telegram token hidden]', text)
    text = re.sub(r'\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b', '[credential hidden]', text)
    text = re.sub(r'(?i)(\bAuthorization\s*[:=]\s*[\"\']?\s*(?:Bearer|Basic)\s+)[^\s\"\'<>]+', r'\1[hidden]', text)
    text = re.sub(r'(https?://[^\s/:@]+:)[^\s/@]+(@)', r'\1[hidden]\2', text)
    text = re.sub(r'''(?i)(["'][A-Z_]*(?:TOKEN|PASSWORD|SECRET|API_KEY)[A-Z_]*["']\s*:\s*)(?:"[^"\r\n]*"|'[^'\r\n]*')''', r'\1"[hidden]"', text)
    # Environment assignments, JSON/config values, and added diff lines.
    text = re.sub(r"(?im)^(\s*[+\-]?\s*(?:export\s+)?[\"']?[A-Z_]*(?:TOKEN|PASSWORD|SECRET|API_KEY)[A-Z_]*[\"']?\s*[:=]\s*).+$", r'\1[hidden]', text)
    return text


def public_value(value):
    if isinstance(value, str):
        return public_text(value)
    if isinstance(value, list):
        return [public_value(item) for item in value]
    if isinstance(value, dict):
        return {key: public_value(item) for key, item in value.items()}
    return value


def response_body(body):
    # Protocol identity and hashes must retain their exact values.
    return {**body, 'events': public_value(body.get('events', []))}
