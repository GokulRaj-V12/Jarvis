# Telegram DNS Networking Errors Reference

This document summarizes the persistent networking issues encountered during the deployment of the Jarvis AI assistant to Hugging Face (HF) Spaces. 

## Primary Error
`telegram.error.NetworkError: httpx.ConnectError: [Errno -5] No address associated with hostname`

## The Problem
Hugging Face's containerized infrastructure (specifically the DNS resolution system) had trouble resolving `api.telegram.org`. 

### Symptoms
1.  **Resolved but failed:** Sometimes `socket.getaddrinfo` would correctly resolve to `149.154.166.110`, but `httpx` and `anyio` would still throw a `[Errno -5]` error. 
2.  **Protocol Block:** HF subnets often have restricted IPv6 support, causing resolution failures when libraries attempt the modern protocol first. 
3.  **Proxy Interference:** Hidden proxy settings in the environment were found to be hijacking connection attempts and failing to resolve the destination.

## Attempted Fixes (Summary)
1.  **Monkeypatching `socket.getaddrinfo`**: Attempted to force IP-level resolution via Google/Cloudflare DNS. 
2.  **HTTPX Transport (IPv4 Only)**: Forced `local_address="0.0.0.0"` and `trust_env=False`. 
3.  **The "Nuclear Option"**: Hardcoded the stable IP of Telegram (`149.154.166.110`) and skipped SSL hostname verification. 
4.  **Background Retries**: Added background retry logic to prevent the build from timing out during deployment. 

## Decision to Pivot
While some of the above fixes partially worked, the complexity and fragility of maintaining a bot in a non-compliant network led us to pivot to **Discord**, which is more cloud-native and typically more stable on Hugging Face. 
