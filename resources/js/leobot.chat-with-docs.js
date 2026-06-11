// 1. Configuration & Default Data
const ENDPOINT_URL =  "https://multi-source-agent-667689422404.asia-south1.run.app";

const defaultData = {
  urls: [
    "https://www.delve.ai/blog/ai-for-marketing",
    "https://fpt.ai/vi/bai-viet/agentic-ai/",
    "https://www.brandsvietnam.com/congdong/topic/341812-10-ung-dung-cua-ai-trong-marketing-cases-study-tu-cac-thuong-hieu-lego-nutella-heinz-coca-cola"
  ],
  question: "Định nghĩa agentic-ai, cho 5 use cases AI cho marketing ",
};

$(document).ready(function () {
  // 2. Initialize UI with Default Data
  initUI(defaultData);

  // 3. Event: Add Source URL
  $("#add-url-btn").on("click", function () {
    addUrlField("");
  });

  // 4. Event: Remove Source URL (Event Delegation for dynamic elements)
  $("#url-container").on("click", ".remove-url", function () {
    // Ensure at least one input remains is usually good UX, but allowed to clear all here
    $(this).closest(".input-group").remove();
  });

  // 5. Event: Submit "Think & Answer"
  $("#submit-btn").on("click", function () {
    handleSubmission();
  });
});

/**
 * Function to populate the UI on load
 */
function initUI(data) {
  // Clear container
  $("#url-container").empty();

  // Populate URLs
  if (data.urls && data.urls.length > 0) {
    data.urls.forEach((url) => {
      addUrlField(url);
    });
  } else {
    addUrlField(""); // Add one empty field if none exist
  }

  // Populate Question
  $("#question-input").val(data.question);
}

/**
 * Helper to create HTML for a URL Input
 */
function addUrlField(value) {
  const html = `
            <div class="input-group mb-2 url-entry">
                <span class="input-group-text"><i class="fas fa-link"></i></span>
                <input type="text" class="form-control url-input" placeholder="https://..." value="${value}">
                <button class="btn btn-outline-danger remove-url" type="button" title="Remove">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        `;
  $("#url-container").append(html);
}

/**
 * Core Function: Build JSON and Submit
 */
function handleSubmission() {
  const $btn = $("#submit-btn");
  const $responseArea = $("#response-area");

  // 1. Build Payload
  let collectedUrls = [];
  $(".url-input").each(function () {
    const val = $(this).val().trim();
    if (val) collectedUrls.push(val);
  });

  const questionVal = $("#question-input").val().trim();

  // Validation
  if (collectedUrls.length === 0) {
    alert("Please provide at least one source URL.");
    return;
  }
  if (!questionVal) {
    alert("Please enter a question.");
    return;
  }

  const payload = {
    urls: collectedUrls,
    question: questionVal,
  };

  // 2. Set Loading State
  $btn
    .prop("disabled", true)
    .html('<i class="fas fa-spinner fa-spin me-2"></i> Thinking...');
  $responseArea.hide().text("");

  console.log("Submitting Payload:", JSON.stringify(payload));

  // 3. AJAX Request
  $.ajax({
    url: ENDPOINT_URL,
    type: "POST",
    contentType: "application/json",
    data: JSON.stringify(payload),
    success: function (response) {
      // Handle Success
      $responseArea.show();
      displayAnswer(response);
    },
    error: function (xhr, status, error) {
      // Handle Error
      console.error("Error:", error);
      $responseArea.show();
      $responseArea.html(
        `<span class="text-danger">Error: ${xhr.status} ${xhr.statusText} - Check console for details.</span>`
      );
    },
    complete: function () {
      // Reset Button
      $btn
        .prop("disabled", false)
        .html('<i class="fas fa-brain me-2"></i> Think & Answer');
    },
  });
}

/**
 * Handles Markdown conversion and link attributes
 */
function displayAnswer(response) {
  const $responseArea = $("#response-area");
  let rawMarkdown = "";

  // 1. Safe extraction of the answer string
  if (typeof response === "object") {
    // Priority: response.answer -> response.message -> JSON string
    rawMarkdown = response.answer;
  } else {
    rawMarkdown = response;
  }

  // Convert Markdown to HTML
  let htmlContent = marked.parse(rawMarkdown);

  // 3. Process HTML to add target="_blank" to all links
  // We create a temporary jQuery object to manipulate the DOM elements easily
  let $tempContainer = $("<div>").html(htmlContent);

  $tempContainer.find("a").attr("target", "_blank");

  // 4. Render final HTML
  $responseArea.html($tempContainer.html());
}
