var currentUserProfile = {
  visitorId: "",
  displayName: "friend",
  touchpointId: "",
  latitude: null,
  longitude: null,
};


function loadChatSessionWithProfile() {
  let userProfile = {};
  const hashData = location.hash.substring(1);
  try {
    userProfile = hashData ? JSON.parse(decodeURIComponent(hashData)) : {};
    console.log("Loaded user profile from hash:", userProfile);
  } catch (e) {
    console.warn("Invalid profile data in hash:", e);
    userProfile = {};
  }

  // === You can now use `userProfile` to personalize the chatbot ===
  // Example:
  // if (userProfile.name) greetUser(userProfile.name);
}

// Call when location.hash changes (e.g., updated by parent page)
window.addEventListener("hashchange", loadChatSessionWithProfile);

window.leoBotUI = false;
window.leoBotContext = false;
function getBotUI() {
  if (window.leoBotUI === false) {
    window.leoBotUI = new BotUI("LEO_ChatBot_Container");
  }
  return window.leoBotUI;
}

function buildUserProfileUrl(visitorId) {
  var url = BASE_URL_GET_VISITOR_INFO +"?visitor_id=" + visitorId + "&_=" + new Date().getTime();
  return url;
}

function touchpointCacheKey(visitorId) {
  return "touchpoint_id_" + visitorId;
}

function requestUserGeolocation(visitorId) {
  if (!navigator.geolocation || typeof BASE_URL_TOUCHPOINT === "undefined") {
    return Promise.resolve(null);
  }

  return new Promise(function (resolve) {
    navigator.geolocation.getCurrentPosition(
      function (position) {
        var payload = {
          visitor_id: visitorId,
          name: document.title || "Web visitor",
          description: "Browser geolocation touchpoint",
          type: "web",
          keywords: [window.location.hostname],
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          touchpoint_id:
            currentUserProfile.touchpointId ||
            lscache.get(touchpointCacheKey(visitorId)) ||
            null,
        };
        $.ajax({
          url: BASE_URL_TOUCHPOINT,
          type: "POST",
          contentType: "application/json",
          data: JSON.stringify(payload),
        })
          .done(function (data) {
            currentUserProfile.touchpointId = data.touchpoint_id || "";
            currentUserProfile.latitude = data.latitude;
            currentUserProfile.longitude = data.longitude;
            if (currentUserProfile.touchpointId) {
              lscache.set(
                touchpointCacheKey(visitorId),
                currentUserProfile.touchpointId
              );
            }
            console.info("Location-aware touchpoint ready", data.touchpoint_id);
            resolve(data);
          })
          .fail(function () {
            console.warn("Unable to create location touchpoint.");
            resolve(null);
          });
      },
      function (error) {
        console.info("Geolocation unavailable or denied:", error.message);
        resolve(null);
      },
      { enableHighAccuracy: false, maximumAge: 300000, timeout: 10000 }
    );
  });
}

function initLeoChatBot(context, visitorId, okCallback) {
  window.leoBotContext = context;
  window.currentUserProfile.visitorId = visitorId;
  currentUserProfile.touchpointId =
    lscache.get(touchpointCacheKey(visitorId)) || "";
  window.leoBotUI = new BotUI("LEO_ChatBot_Container");

  loadChatSessionWithProfile()
  Promise.all([
    requestUserGeolocation(visitorId),
    new Promise(function (resolve) {
      $.getJSON(buildUserProfileUrl(visitorId), resolve).fail(function () {
        resolve({ error_code: 500 });
      });
    }),
  ]).then(function (results) {
    var data = results[1];
    var error_code = data.error_code;
    var name = data.name;
    console.log(data);

    if (error_code === 0 && typeof name === "string") {      
      currentUserProfile.displayName = name;
      showLeoChatBot(currentUserProfile.displayName);
    } 
    else if (error_code === 404) {
      // askTheContactOfUser();
      currentUserProfile.displayName = '';
      showLeoChatBot(currentUserProfile.displayName);
    } 
    else {
      leoBotShowError(data, leoBotPromptQuestion);
    }
  });

  if (typeof okCallback === "function") {
    okCallback();
  }
}

/**
 * Returns a greeting message in either English or Vietnamese.
 *
 * @param {string} displayName The name of the user to greet.
 * @param {string} language The language code ('en' for English, 'vi' for Vietnamese).
 * @returns {string} The formatted greeting message.
 */
function getGreetingMessage(displayName, language) {
  let msg;
  switch (language) {
    case 'vi':
      msg = "Chào " + displayName + ", bạn có thể hỏi tôi bất cứ điều gì";
      break;
    case 'en':
    default: // Default to English if the language is not recognized
      msg = "Hi " + displayName + ", you may ask me for anything";
      break;
  }
  return msg;
}

var showLeoChatBot = function (displayName) {
  var msg = getGreetingMessage(displayName, "vi");
  var msgObj = { content: msg, cssClass: "leobot-answer" };
  getBotUI().message.removeAll();
  getBotUI().message.bot(msgObj).then(leoBotPromptQuestion);
};

var leoBotPromptQuestion = function (delay) {
  getBotUI()
    .action.text({
      delay: typeof delay === "number" ? delay : 800,
      action: {
        icon: "question-circle",
        cssClass: "leobot-question-input",
        value: "", // show the prevous answer if any
        placeholder: "..................",
      },
    })
    .then(function (res) {
      sendQuestionToLeoAI("ask", res.value);
    });
};

var processMessageNode  = function(rawAnswer) {
  var node_id = 'm_'  + getRandomStrWithTime()
  if(rawAnswer.indexOf("<html>") >= 0){
    var iframe = document.createElement('iframe');
    iframe.setAttribute('id',node_id)
    iframe.style.width = "100%";
    iframe.style.height = "400px";
    iframe.style.border = "1px solid #ddd";
    iframe.style.borderRadius = "6px";

    return {'html':iframe.outerHTML,'type':'iframe','id': node_id};
  } 
  else {
    var container = document.createElement('div');
    container.setAttribute('id',node_id)
    container.innerHTML = marked.parse(rawAnswer)
    return {'html':container.outerHTML,'type':'div','id': node_id};
  }
}

function getRandomStrWithTime(length = 10) {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let randomPart = '';
  for (let i = 0; i < length; i++) {
    randomPart += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  const timestamp = Date.now().toString(36); // base36 makes it shorter & still sortable
  return `${randomPart}_${timestamp}`;
}

var leoBotShowAnswer = function (rawAnswer, providedDelay) {
  
  var node = processMessageNode(rawAnswer);
  getBotUI()
    .message.add({
      human: false,
      cssClass: "leobot-answer",
      content: node.html,
      type: "html",
    })
    .then(function () {
      if(node.type === 'iframe') {
          var iframe = document.getElementById(node.id)
          const doc = iframe.contentDocument || iframe.contentWindow.document;
          doc.open();
          doc.write(rawAnswer);
          doc.close();

          $(iframe).parent().parent().removeClass('botui-message-content').addClass('botui-message-report')
      }

      // format all href nodes in answer
      $("div.botui-message")
        .find("a")
        .each(function () {
          $(this).attr("target", "_blank");
          $(this).attr("rel", "noopener noreferrer");
          var href = $(this).attr("href") || "";
          if (href.indexOf("google.com") < 0) {
            href =
              "https://www.google.com/search?q=" +
              encodeURIComponent($(this).text());
          }
          $(this).attr("href", href);
        });

      let delay;
      if (typeof providedDelay === "number") {
        delay = providedDelay;
      } else if (rawAnswer.length > 200) {
        delay = 3000;
      } else {
        delay = 1500;
      }
      leoBotPromptQuestion(delay);
    });
};

var leoBotShowError = function (error, nextAction) {
  getBotUI()
    .message.add({
      human: false,
      cssClass: "leobot-error",
      content: error,
      type: "html",
    })
    .then(nextAction || function () {});
};

function isEmailValid(email) {
  const regex =
    /^(([^<>()[\]\\.,;:\s@\"]+(\.[^<>()[\]\\.,;:\s@\"]+)*)|(\".+\"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/;
  return regex.test(email);
}

var askTheEmailOfUser = function (name) {
  getBotUI()
    .action.text({
      delay: 0,
      action: {
        icon: "envelope-o",
        cssClass: "leobot-question-input",
        value: "",
        placeholder: "Email của bạn",
      },
    })
    .then(function (res) {
      var email = res.value;
      if (isEmailValid(email)) {
        console.log(name, email);
        var profileData = {
          loginProvider: "leochatbot",
          firstName: name,
          email: email,
        };
        if(window.CDP_TRACKING === true) {
          LeoObserverProxy.updateProfileBySession(profileData);
        }

        setTimeout(function () {
          location.reload(true);
        }, 3000);

        var s = "Chào " +  name + ", hệ thống đang đăng ký thông tin cho bạn ...";
        leoBotShowAnswer(s, 6000);// delay 10 seconds to make chatbot do not show input box
      } else {
        leoBotShowError(email + " không là email hợp lệ", function () {
          askTheEmailOfUser(name);
        });
      }
    });
};

var askTheNameOfUser = function () {
  getBotUI()
    .action.text({
      delay: 0,
      action: {
        icon: "user-circle-o",
        cssClass: "leobot-question-input",
        value: "",
        placeholder: "Tên bạn",
      },
    })
    .then(function (res) {
      askTheEmailOfUser(res.value);
    });
};

var askTheContactOfUser = function () {
  var msg = "Chào bạn, vui lòng nhập tên và email để  cần hỗ trỡ";
  getBotUI()
    .message.add({
      human: false,
      cssClass: "leobot-question",
      content: msg,
      type: "html",
    })
    .then(askTheNameOfUser);
};

var sendQuestionToLeoAI = function (context, question) {
  question = typeof question === "string" ? question.trim() : "";
  if (!question) {
    leoBotShowError("Vui lòng nhập câu hỏi hoặc số của địa điểm.", leoBotPromptQuestion);
    return;
  }
  if (question !== "exit") {

    //
    var processAnswer = function (answer) {
      if ("ask" === context) {
        leoBotShowAnswer(answer);
      }
      // save event into CDP
      if (typeof LeoObserver === "object" && CDP_TRACKING === true) {
        var sAnswer = answer.slice(0, 1000);
        var eventData = { question: question, answer: sAnswer };
        LeoObserver.recordEventAskQuestion(eventData);
      } else {
        console.log("SKIP LeoObserver.recordEventAskQuestion")
      }
    };

    var callServer = function (index) {
      var serverCallback = function (data) {
        getBotUI().message.remove(index);
        var error_code = data.error_code;
        var answer = data.answer;
        if (error_code === 0) {
          currentUserProfile.displayName = data.name || currentUserProfile.displayName;
          if (data.touchpoint_id) {
            currentUserProfile.touchpointId = data.touchpoint_id;
            lscache.set(
              touchpointCacheKey(currentUserProfile.visitorId),
              data.touchpoint_id
            );
          }
          processAnswer(answer);
        } else if (error_code === 404) {
          // askTheContactOfUser();
          currentUserProfile.displayName = "";
          processAnswer(answer);
        } else {
          leoBotShowError(answer, leoBotPromptQuestion);
        }
      };

      var context = $('#LEO_ChatBot_Container').find('.botui-message-content').slice(-3)
              .map(function () {
                return $(this).text();
              }).get().join(' ; ');

      var payload = {};
      payload["context"] = context;
      payload["question"] = question;
      payload["visitor_id"] = currentUserProfile.visitorId;
      payload["touchpoint_id"] = currentUserProfile.touchpointId || null;
      payload["latitude"] = currentUserProfile.latitude;
      payload["longitude"] = currentUserProfile.longitude;
      payload["answer_in_language"] = "Vietnamese";
      payload["answer_in_format"] = "html";
      
      callPostApi(BASE_URL_LEOBOT, payload, serverCallback, function () {
        getBotUI().message.remove(index);
        leoBotShowError(
          "Không thể gửi tin nhắn. Vui lòng thử lại.",
          leoBotPromptQuestion
        );
      });
    };
    showChatBotLoader().then(callServer);
  }
};

var showChatBotLoader = function () {
  return getBotUI().message.add({ loading: true, content: "" });
};

var callPostApi = function (urlStr, data, okCallback, errorCallback) {
  $.ajax({
    url: urlStr,
    crossDomain: true,
    data: JSON.stringify(data),
    contentType: "application/json",
    type: "POST",
    error: function (jqXHR, exception) {
      console.error("WE GET AN ERROR AT URL:" + urlStr);
      console.error(exception);
      if (typeof errorCallback === "function") {
        errorCallback();
      }
    },
  }).done(function (json) {
    okCallback(json);
    console.log("callPostApi", urlStr, data, json);
  });
};


// Generate RFC4122 v4 UUID (36 chars, standard)
function generateUUID() {
  return ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, c =>
    (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16)
  );
}

// Retrieve or create visitor ID with expiration
async function getVisitorId(ttlDays = 365) {
  let id = lscache.get('visitor_id');

  if (!id) {
    id = generateUUID();

    // Store with TTL (days)
    lscache.set('visitor_id', id);

    // Fallback cookie (optional)
    document.cookie = `visitor_id=${id}; path=/; max-age=${ttlDays * 24 * 60 * 60}`;
  }

  return id;
}


var startLeoChatBot = function (visitorId) {
  lscache.setBucket('leobot');
  
  var setupChatBot = function (vid) {
    currentUserProfile.visitorId = vid;
    $("#LEO_ChatBot_Container_Loader").hide();
    $("#LEO_ChatBot_Container").show();
    initLeoChatBot("leobot_website", vid);
  }

  if( visitorId === undefined) {
    getVisitorId().then(id => {
      console.log("startLeoChatBot with Visitor ID:", id);
      setupChatBot(id);
    });
  }
  else {
    console.log("startLeoChatBot with Visitor ID:", visitorId);
    setupChatBot(visitorId);
  }

};
