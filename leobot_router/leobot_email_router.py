import logging
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from leoai.email_sender import EmailSender
from leoai.rag_context_utils import get_base_context
from main_config import get_current_user

# Dedicated router for email-related endpoints
logger = logging.getLogger("leobot-email")
router = APIRouter()


@router.post("/_leoai/email-agent", response_class=JSONResponse)
async def email_agent(request: Request, user: str = Depends(get_current_user)):
    """
    AI-powered Email Agent endpoint.
    Handles dynamic, templated email sending via SMTP.

    Expected JSON payload:
    {
        "to_email": "recipient@example.com",
        "subject": "Custom Subject (optional)",
        "template_name": "template.html",
        "context": {...}  // Optional dynamic context
    }
    """
    try:
        # Parse JSON input
        data = await request.json()

        # Initialize EmailSender class (handles template rendering + SMTP)
        agent = EmailSender()

        # Merge provided data with base context
        context = get_base_context(data)

        # Resolve recipient and metadata
        to_email = data.get("to_email") or context.get("user_profile", {}).get("primary_email")
        subject = data.get("subject", "AI Agent Email")
        template_name = data.get("template_name", "welcome_email.html")

        # Validation
        if not to_email:
            return JSONResponse(status_code=400, content={"error": "Recipient email not provided"})

        # Send the email asynchronously
        success = await agent.send(to_email, subject, template_name, context)

        # Check result
        if not success:
            return JSONResponse(status_code=500, content={"error": "Failed to send email"})

        logger.info(f"✅ Email successfully sent to {to_email}")
        return {"ok": True, "message": "Email sent successfully"}

    except Exception:
        # Log details server-side without exposing implementation or SMTP errors.
        logger.exception("Email agent error")
        return JSONResponse(status_code=500, content={"error": "Email processing failed"})
