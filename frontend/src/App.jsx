
import { useEffect, useRef, useState } from "react";
import "./App.css";

// const API_URL = "http://127.0.0.1:8000";
const API_URL = "https://noteassistant-v1-backend.onrender.com";

const ALLOWED_FILE_TYPES = [
  ".pdf",
  ".docx",
  ".txt",
  ".png",
  ".jpg",
  ".jpeg"
];

const UPLOAD_WORDS = [
  "Extracting",
  "Converting",
  "Chunking",
  "Embedding",
  "Storing"
];

const THINKING_WORDS = [
  "Thinking",
  "Understanding",
  "Searching",
  "Reasoning",
  "Responding"
];

function generateMessageId() {
  return crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function getFriendlyError(error) {
  const message = error?.message || "";

  if (
    message.includes("Failed to fetch") ||
    message.includes("NetworkError") ||
    message.includes("fetch")
  ) {
    return "Unable to connect to Note Assistant. Please make sure the backend is running and try again.";
  }

  return message || "Something went wrong. Please try again.";
}

function formatDocumentSummary(content) {
  if (!content) return content;

  const isDocumentSummary =
    /^\s{0,3}#{1,6}\s*Summary\s*$/im.test(content);

  if (!isDocumentSummary) return content;

  let formatted = content;

  formatted = formatted.replace(
    /^\s{0,3}#{1,6}\s*Follow[- ]?up\s*:?\s*$/im,
    ""
  );

  formatted = formatted.replace(/^\s{0,3}#{1,6}\s*/gm, "");
  formatted = formatted.replace(/\*\*(.*?)\*\*/g, "$1");
  formatted = formatted.replace(/__(.*?)__/g, "$1");
  formatted = formatted.replace(/\*(.*?)\*/g, "$1");
  formatted = formatted.replace(/_(.*?)_/g, "$1");
  formatted = formatted.replace(/^\s*[-*+]\s+/gm, "");
  formatted = formatted.replace(/^\s*\d+[.)]\s+/gm, "");
  formatted = formatted.replace(/[ \t]+\n/g, "\n");
  formatted = formatted.replace(/\n{3,}/g, "\n\n");

  return formatted.trim();
}

function getFileExtension(filename = "") {
  return filename.split(".").pop()?.toUpperCase() || "FILE";
}

function formatFileSize(bytes) {
  if (!bytes) return "";

  if (bytes < 1024) {
    return `${bytes} bytes`;
  }

  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }

  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function DocumentCard({ metadata }) {
  if (!metadata || metadata.type !== "document") {
    return null;
  }

  return (
    <div className="document-card">
      <div className="document-card-details">
        <div className="document-card-name">
          {metadata.filename || "Uploaded document"}
        </div>

        <div className="document-card-info">
          <span>{getFileExtension(metadata.filename)}</span>

          {metadata.file_size > 0 && (
            <>
              <span>•</span>
              <span>{formatFileSize(metadata.file_size)}</span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function App() {
  const [messages, setMessages] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);

  const [input, setInput] = useState("");
  const [selectedFile, setSelectedFile] = useState(null);
  const [isListening, setIsListening] = useState(false);

  const [isSending, setIsSending] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [isCreatingConversation, setIsCreatingConversation] = useState(false);

  const [isSidebarOpen, setIsSidebarOpen] = useState(
    () => window.innerWidth > 650
  );

  const [isConversationListExpanded, setIsConversationListExpanded] =
    useState(true);

  const [statusWord, setStatusWord] = useState("Thinking");
  const [error, setError] = useState("");

  const isBusy =
    isSending ||
    isUploading ||
    isLoadingMessages ||
    isCreatingConversation;

  const fileInputRef = useRef(null);
  const recognitionRef = useRef(null);
  const messagesEndRef = useRef(null);

  const sendingRef = useRef(false);
  const initializationRef = useRef(false);
  const creatingConversationRef = useRef(false);

  // ------------------------------------------
  // MESSAGE HELPERS
  // ------------------------------------------

  function createMessage(
    role,
    content,
    metadata = {},
    messageId = generateMessageId()
  ) {
    return {
      id: messageId,
      client_message_id: messageId,
      role,
      content,
      metadata,
      created_at: new Date().toISOString()
    };
  }

  function normalizeMessages(data) {
    if (!Array.isArray(data)) return [];

    return data.map((message) => {
      const messageId =
        message.client_message_id ||
        message.id ||
        generateMessageId();

      return {
        ...message,
        id: message.id || messageId,
        client_message_id: messageId,
        metadata: message.metadata || {},
        created_at:
          message.created_at || new Date().toISOString()
      };
    });
  }

  function getCurrentHistory() {
    return messages;
  }

  // ------------------------------------------
  // SIDEBAR
  // ------------------------------------------

  function closeSidebar() {
    if (window.innerWidth <= 650) {
      setIsSidebarOpen(false);
    }
  }

  function toggleSidebar() {
    setIsSidebarOpen((previous) => !previous);
  }

  function toggleConversationList() {
    setIsConversationListExpanded((previous) => !previous);
  }

  // ------------------------------------------
  // INITIALIZATION
  // ------------------------------------------

  useEffect(() => {
    if (initializationRef.current) return;

    initializationRef.current = true;
    initializeConversations();
  }, []);

  useEffect(() => {
    if (!isUploading) return;

    let currentIndex = 0;

    setStatusWord(UPLOAD_WORDS[currentIndex]);

    const interval = setInterval(() => {
      currentIndex = (currentIndex + 1) % UPLOAD_WORDS.length;
      setStatusWord(UPLOAD_WORDS[currentIndex]);
    }, 1500);

    return () => clearInterval(interval);
  }, [isUploading]);

  useEffect(() => {
    if (!isThinking) return;

    let currentIndex = 0;

    setStatusWord(THINKING_WORDS[currentIndex]);

    const interval = setInterval(() => {
      currentIndex = (currentIndex + 1) % THINKING_WORDS.length;
      setStatusWord(THINKING_WORDS[currentIndex]);
    }, 1500);

    return () => clearInterval(interval);
  }, [isThinking]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({
      behavior: "smooth"
    });
  }, [messages, isThinking, isUploading, statusWord]);

  // ------------------------------------------
  // LOAD CONVERSATIONS
  // ------------------------------------------

  async function loadConversations() {
    try {
      const response = await fetch(`${API_URL}/conversations`);

      if (!response.ok) {
        throw new Error("Could not load conversations");
      }

      const data = await response.json();

      setConversations(data);

      return data;
    } catch (error) {
      setError(getFriendlyError(error));
      return [];
    }
  }

  async function loadConversationMessages(conversationId) {
    const response = await fetch(
      `${API_URL}/conversations/${conversationId}/messages`
    );

    if (!response.ok) {
      throw new Error("Could not load conversation messages");
    }

    const data = await response.json();

    return normalizeMessages(data);
  }

  async function initializeConversations() {
    setIsLoadingMessages(true);

    try {
      const data = await loadConversations();

      if (data.length === 0) {
        setMessages([]);
        setActiveConversationId(null);
        return;
      }

      const latestConversation = data[0];

      const restoredMessages = await loadConversationMessages(
        latestConversation.id
      );

      setMessages(restoredMessages);
      setActiveConversationId(latestConversation.id);
      setSelectedFile(null);
    } catch (error) {
      setError(getFriendlyError(error));
    } finally {
      setIsLoadingMessages(false);
    }
  }

  // ------------------------------------------
  // CREATE CONVERSATION
  // ------------------------------------------

  async function createNewConversation(preserveMessages = false) {
    if (creatingConversationRef.current) {
      return null;
    }

    creatingConversationRef.current = true;
    setIsCreatingConversation(true);

    try {
      const response = await fetch(`${API_URL}/conversations`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          title: "New Conversation"
        })
      });

      if (!response.ok) {
        throw new Error("Could not create conversation");
      }

      const conversation = await response.json();

      setActiveConversationId(conversation.id);

      if (!preserveMessages) {
        setMessages([]);
        setInput("");
      }

      setSelectedFile(null);

      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }

      setError("");

      await loadConversations();

      return conversation.id;
    } catch (error) {
      setError(getFriendlyError(error));
      return null;
    } finally {
      creatingConversationRef.current = false;
      setIsCreatingConversation(false);
    }
  }

  async function handleNewChat() {
    if (isBusy || sendingRef.current) return;

    if (isListening) {
      recognitionRef.current?.stop();
      setIsListening(false);
    }

    setMessages([]);
    setInput("");
    setSelectedFile(null);
    setActiveConversationId(null);
    setError("");

    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }

    const conversationId = await createNewConversation(false);

    if (conversationId) {
      closeSidebar();
    }
  }

  // ------------------------------------------
  // OPEN EXISTING CONVERSATION
  // ------------------------------------------

  async function openConversation(conversationId) {
    if (isBusy || sendingRef.current) return;

    setIsLoadingMessages(true);
    setError("");

    try {
      const restoredMessages =
        await loadConversationMessages(conversationId);

      setMessages(restoredMessages);
      setActiveConversationId(conversationId);
      setSelectedFile(null);

      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }

      closeSidebar();
    } catch (error) {
      setError(getFriendlyError(error));
    } finally {
      setIsLoadingMessages(false);
    }
  }

  // ------------------------------------------
  // DOCUMENT UPLOAD
  // ------------------------------------------

  async function uploadSelectedFile(
    conversationId,
    file,
    userMessageId,
    content = ""
  ) {
    setIsUploading(true);

    const metadata = {
      type: "document",
      filename: file.name,
      content_type: file.type,
      file_size: file.size
    };

    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await fetch(
        `${API_URL}/conversations/${conversationId}/upload`,
        {
          method: "POST",
          body: formData
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Document upload failed");
      }

      const assistantContent =
        data.status === "stored"
          ? data.summary
          : `${file.name} received successfully. ${data.note || ""}`;

      if (!assistantContent) {
        throw new Error(
          "Document was stored, but the summary was not returned by the backend."
        );
      }

      metadata.document_id = data.document_id || null;
      metadata.total_chunks = data.total_chunks || 0;

      const updatedUserMessage = {
        id: userMessageId,
        client_message_id: userMessageId,
        role: "user",
        content,
        metadata,
        created_at: new Date().toISOString()
      };

      const assistantMessage = data.assistant_message
        ? {
            ...data.assistant_message,
            metadata: {
              ...(data.assistant_message.metadata || {}),
              ...metadata
            }
          }
        : createMessage(
            "assistant",
            assistantContent,
            metadata
          );

      setMessages((previous) => {
        const updated = previous.map((message) =>
          message.id === userMessageId
            ? updatedUserMessage
            : message
        );

        return [...updated, assistantMessage];
      });

      return {
        metadata,
        assistantMessage
      };
    } finally {
      setIsUploading(false);
    }
  }

  // ------------------------------------------
  // SEND MESSAGE
  // ------------------------------------------

  async function handleSend() {
    if (sendingRef.current) return;

    const content = input.trim();
    const file = selectedFile;

    if ((!content && !file) || isBusy) return;

    sendingRef.current = true;

    setIsSending(true);
    setError("");
    setInput("");

    const userMessageId = generateMessageId();

    const initialMetadata = file
      ? {
          type: "document",
          filename: file.name,
          content_type: file.type,
          file_size: file.size
        }
      : {};

    const userMessage = createMessage(
      "user",
      content,
      initialMetadata,
      userMessageId
    );

    // Capture current React history before updating state.
    const previousHistory = getCurrentHistory();

    // Display the user's message immediately.
    setMessages((previous) => [
      ...previous,
      userMessage
    ]);

    try {
      let conversationId = activeConversationId;

      if (!conversationId) {
        conversationId = await createNewConversation(true);

        if (!conversationId) {
          throw new Error(
            "Unable to create your conversation. Please check whether the backend is running."
          );
        }
      }

      // The current conversation history exists in React state.
      let currentHistory = [
        ...previousHistory,
        userMessage
      ];

      if (file) {
        const uploadResult = await uploadSelectedFile(
          conversationId,
          file,
          userMessageId,
          content
        );

        currentHistory = [
          ...currentHistory.map((message) =>
            message.id === userMessageId
              ? {
                  ...message,
                  metadata: uploadResult.metadata
                }
              : message
          ),
          uploadResult.assistantMessage
        ];

        setSelectedFile(null);

        if (fileInputRef.current) {
          fileInputRef.current.value = "";
        }
      }

      if (content) {
        setIsThinking(true);

        try {
          const history = currentHistory.map((message) => ({
            id: message.id,
            client_message_id:
              message.client_message_id || message.id,
            role: message.role,
            content: message.content,
            metadata: message.metadata || {}
          }));

          const response = await fetch(
            `${API_URL}/conversations/${conversationId}/chat`,
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json"
              },
              body: JSON.stringify({
                content,
                history
              })
            }
          );

          const data = await response.json();

          if (!response.ok) {
            throw new Error(
              data.detail || "Could not get assistant response"
            );
          }

          const updatedUserMessage = {
            ...userMessage,
            content: data.user_message.content,
            metadata: {
              ...(data.user_message.metadata || {}),
              ...(userMessage.metadata || {})
            }
          };

          const assistantMessage = {
            ...data.assistant_message,
            id:
              data.assistant_message.id ||
              generateMessageId(),
            client_message_id:
              data.assistant_message.client_message_id ||
              data.assistant_message.id ||
              generateMessageId(),
            metadata: data.assistant_message.metadata || {},
            created_at:
              data.assistant_message.created_at ||
              new Date().toISOString()
          };

          setMessages((previous) => {
            const updated = previous.map((message) =>
              message.id === userMessageId
                ? updatedUserMessage
                : message
            );

            return [
              ...updated,
              assistantMessage
            ];
          });
        } finally {
          setIsThinking(false);
        }
      }

      await loadConversations();
    } catch (error) {
      setError(getFriendlyError(error));

      // Keep the user's message visible in React state.
      // It is not automatically persisted to PostgreSQL.
      if (content) {
        setInput(content);
      }
    } finally {
      setIsThinking(false);
      setIsSending(false);
      setIsUploading(false);

      sendingRef.current = false;
    }
  }

  // ------------------------------------------
  // FILE VALIDATION
  // ------------------------------------------

  function handleFileSelect(event) {
    const file = event.target.files?.[0];

    if (!file) return;

    const fileName = file.name.toLowerCase();

    const isAllowed = ALLOWED_FILE_TYPES.some((extension) =>
      fileName.endsWith(extension)
    );

    if (!isAllowed) {
      setError(
        "Unsupported file type. Please select PDF, DOCX, TXT, PNG or JPG."
      );

      event.target.value = "";
      setSelectedFile(null);
      return;
    }

    if (file.size > 10 * 1024 * 1024) {
      setError("File size cannot exceed 10 MB.");
      event.target.value = "";
      setSelectedFile(null);
      return;
    }

    setError("");
    setSelectedFile(file);
  }

  function removeSelectedFile() {
    setSelectedFile(null);

    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }

  // ------------------------------------------
  // MICROPHONE
  // ------------------------------------------

  function handleMicrophone() {
    const SpeechRecognition =
      window.SpeechRecognition ||
      window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
      alert("Speech recognition is not supported in this browser.");
      return;
    }

    if (isListening) {
      recognitionRef.current?.stop();
      setIsListening(false);
      return;
    }

    const recognition = new SpeechRecognition();

    recognition.lang = "en-IN";
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      setInput((previous) => `${previous} ${transcript}`.trim());
    };

    recognition.onerror = () => setIsListening(false);
    recognition.onend = () => setIsListening(false);

    recognitionRef.current = recognition;
    setIsListening(true);
    recognition.start();
  }

  // ------------------------------------------
  // UI
  // ------------------------------------------

  return (
    <div className="app-container">

      {/* Mobile overlay */}
      {isSidebarOpen && (
        <div
          className="sidebar-overlay"
          onClick={closeSidebar}
          aria-hidden="true"
        />
      )}

      {/* Sidebar */}
      <aside
        className={`sidebar ${
          isSidebarOpen ? "sidebar-open" : "sidebar-closed"
        }`}
      >
        <h2>Note Assistant</h2>

        <button
          className="new-chat-button"
          onClick={handleNewChat}
          disabled={isBusy}
        >
          + New Chat
        </button>

        <div className="conversation-list">

          <button
            className="conversation-list-header"
            onClick={toggleConversationList}
            aria-expanded={isConversationListExpanded}
            aria-label={
              isConversationListExpanded
                ? "Collapse recent conversations"
                : "Expand recent conversations"
            }
          >
            <span className="conversation-list-heading">
              <span className="conversation-heading-icon">◷</span>
              Recent conversations
            </span>

            <span
              className={`conversation-expand-icon ${
                isConversationListExpanded ? "expanded" : ""
              }`}
            >
              ⌄
            </span>
          </button>

          {isConversationListExpanded && (
            <div className="conversation-items">

              {conversations.length === 0 ? (
                <p className="no-conversations">
                  No conversations yet
                </p>
              ) : (
                conversations.map((conversation) => (
                  <button
                    key={conversation.id}
                    className={`conversation-item ${
                      activeConversationId === conversation.id
                        ? "active"
                        : ""
                    }`}
                    onClick={() =>
                      openConversation(conversation.id)
                    }
                    disabled={isBusy}
                    title={conversation.title}
                  >
                    

                    <span className="conversation-item-title">
                      {conversation.title}
                    </span>
                  </button>
                ))
              )}

            </div>
          )}
        </div>

        <div className="sidebar-footer">
          Your personal knowledge assistant
        </div>
      </aside>

      {/* Main chat */}
      <main className="chat-container">

        <header className="chat-header">
          <button
            className="menu-toggle"
            onClick={toggleSidebar}
            aria-label={
              isSidebarOpen
                ? "Hide conversations"
                : "Show conversations"
            }
            title={
              isSidebarOpen
                ? "Hide conversations"
                : "Show conversations"
            }
          >
            ☰
          </button>

          <h3>Note Assistant</h3>
        </header>

        <section className="messages-container">

          {messages.length === 0 &&
          !isThinking &&
          !isUploading &&
          !isLoadingMessages &&
          !isCreatingConversation ? (
            <div className="welcome-message">
              <h1>How can I help you today?</h1>
              <p>
                Talk naturally. I'll help you organize your thoughts,
                remember important information, and explore your ideas.
              </p>
            </div>
          ) : (
            messages.map((message) => (
              <div
                key={message.client_message_id || message.id}
                className={`message ${message.role}`}
              >
                <div className="message-role">
                  {message.role === "user" ? "You" : "Assistant"}
                </div>

                {message.metadata?.type === "document" && (
                  <DocumentCard metadata={message.metadata} />
                )}

                {message.content && (
                  <div
                    className="message-content"
                    style={{ whiteSpace: "pre-wrap" }}
                  >
                    {message.role === "assistant"
                      ? formatDocumentSummary(message.content)
                      : message.content}
                  </div>
                )}
              </div>
            ))
          )}

          {(isUploading || isThinking) && (
            <div className="message assistant thinking-message">
              <div className="message-content">
                <div className="animated-status">
                  <span className="upload-stage-spinner" />
                  <span key={statusWord} className="status-word">
                    {statusWord}
                  </span>
                </div>
              </div>
            </div>
          )}

          {(isLoadingMessages || isCreatingConversation) && (
            <div className="message assistant">
              <div className="message-content">
                {isCreatingConversation
                  ? "Creating your conversation..."
                  : "Loading conversation..."}
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </section>

        {error && (
          <p className="error-message" role="alert">
            {error}
          </p>
        )}

        <div className="composer-wrapper">

          {selectedFile && (
            <div className="selected-file">
              <span>{selectedFile.name}</span>

              <button
                onClick={removeSelectedFile}
                title="Remove selected file"
                disabled={isBusy}
              >
                ×
              </button>
            </div>
          )}

          <div className="input-container">

            <input
              type="file"
              ref={fileInputRef}
              hidden
              accept=".pdf,.docx,.txt,.png,.jpg,.jpeg"
              onChange={handleFileSelect}
            />

            <button
              className="icon-button"
              onClick={() => fileInputRef.current?.click()}
              title="Upload PDF, DOCX, TXT or image"
              disabled={isBusy}
            >
              🗁
            </button>

            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  handleSend();
                }
              }}
              placeholder="Message your assistant..."
              rows={1}
              disabled={isBusy}
            />

            <button
              className={`icon-button mic-button ${
                isListening ? "listening" : ""
              }`}
              onClick={handleMicrophone}
              title="Use microphone"
              disabled={isBusy}
            >
              🎙️
            </button>

            <button
              className="send-button"
              onClick={handleSend}
              disabled={(!input.trim() && !selectedFile) || isBusy}
            >
              {isBusy ? "..." : "Send"}
            </button>

          </div>
        </div>

        <p className="input-hint">
          Please verify the response. Note Assistant can make mistakes.
        </p>

      </main>
    </div>
  );
}

export default App;
