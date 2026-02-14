/**
 * Bot Engagement Cloud Functions
 *
 * Handles automatic engagement (likes and comments) on ALL posts:
 * - onPostCreated: Triggered when a new post is created
 *   - Schedules likes from all bot accounts via Cloud Tasks
 *   - Schedules 2 comment tasks via Cloud Tasks with delays
 * - processComment: HTTP function called by Cloud Tasks to post comments
 *   - Comments on ALL posts (no theme filtering)
 *   - Always comments in the same language as the post
 *   - Post text is always the primary context for commenting
 *   - Sounds like a natural spiritual seeker and mentor
 *   - Performs up to 2 web searches for relevant context
 */

const { onDocumentCreated } = require("firebase-functions/v2/firestore");
const { onRequest } = require("firebase-functions/v2/https");
const { logger } = require("firebase-functions/v2");
const admin = require("firebase-admin");
const { CloudTasksClient } = require("@google-cloud/tasks");
const OpenAI = require("openai");

const db = admin.firestore();
const tasksClient = new CloudTasksClient();

// Cache for secrets
let cachedSecrets = null;

/**
 * Get secrets from Firestore config/secrets collection
 */
async function getSecrets() {
    if (cachedSecrets) return cachedSecrets;
    const doc = await db.collection('config').doc('secrets').get();
    if (doc.exists) {
        cachedSecrets = doc.data();
        return cachedSecrets;
    }
    return {};
}

// Constants
const PROJECT_ID = "dhyanapp-90de4";
const LOCATION = "asia-south1";
const QUEUE_NAME = "bot-comments-queue";
const PROCESS_COMMENT_URL = `https://${LOCATION}-${PROJECT_ID}.cloudfunctions.net/processComment`;
const PROCESS_LIKE_URL = `https://${LOCATION}-${PROJECT_ID}.cloudfunctions.net/processLike`;
const LIKE_DELAY_MINUTES = 5; // Delay between each bot's like
const MAX_WEB_SEARCHES = 2; // Maximum web searches per comment generation

/**
 * Get all bot accounts from Firestore
 */
async function getBotAccounts() {
    const doc = await db.collection('botConfig').doc('accounts').get();
    if (!doc.exists) {
        logger.error("Bot accounts config not found in Firestore");
        return {};
    }
    return doc.data().accounts || {};
}

/**
 * Add a like to a post from a bot account
 * Note: likeCount is incremented by the existing handleLikeCreated Cloud Function
 */
async function addLike(postId, userId) {
    try {
        const timestamp = Date.now();
        const likeRef = db.collection('posts').doc(postId).collection('Likes').doc(userId);
        await likeRef.set({
            userId: userId,
            timestamp: timestamp
        });
        logger.info(`Like added to post ${postId} by ${userId}`);
        return true;
    } catch (error) {
        logger.error(`Failed to add like to post ${postId} by ${userId}:`, error);
        return false;
    }
}

/**
 * Add a view to a post from a bot account
 * Increments viewCount on the post document
 */
async function addView(postId, userId) {
    try {
        const postRef = db.collection('posts').doc(postId);

        // Check if this user already viewed (to avoid duplicate views)
        const viewRef = postRef.collection('Views').doc(userId);
        const viewDoc = await viewRef.get();

        if (viewDoc.exists) {
            logger.info(`View already exists for post ${postId} by ${userId}, skipping`);
            return true;
        }

        // Add view document
        const timestamp = Date.now();
        await viewRef.set({
            userId: userId,
            timestamp: timestamp
        });

        // Increment viewCount on the post
        await postRef.update({
            viewCount: admin.firestore.FieldValue.increment(1)
        });

        logger.info(`View added to post ${postId} by ${userId}`);
        return true;
    } catch (error) {
        logger.error(`Failed to add view to post ${postId} by ${userId}:`, error);
        return false;
    }
}

/**
 * Schedule a comment task via Cloud Tasks
 */
async function scheduleCommentTask(postId, botKey, delayMinutes, creatorName, tagBotName) {
    try {
        const queuePath = tasksClient.queuePath(PROJECT_ID, LOCATION, QUEUE_NAME);

        const payload = JSON.stringify({
            postId: postId,
            botKey: botKey,
            creatorName: creatorName || '',
            tagBotName: tagBotName || ''
        });

        const task = {
            httpRequest: {
                httpMethod: 'POST',
                url: PROCESS_COMMENT_URL,
                headers: {
                    'Content-Type': 'application/json',
                },
                body: Buffer.from(payload).toString('base64'),
            },
            scheduleTime: {
                seconds: Math.floor(Date.now() / 1000) + (delayMinutes * 60),
            },
        };

        const [response] = await tasksClient.createTask({ parent: queuePath, task });
        logger.info(`Created comment task for post ${postId}, bot ${botKey}, delay ${delayMinutes}m: ${response.name}`);
        return response.name;
    } catch (error) {
        logger.error(`Failed to schedule comment task for post ${postId}:`, error);
        return null;
    }
}

/**
 * Schedule a like task via Cloud Tasks
 */
async function scheduleLikeTask(postId, botUserId, delayMinutes) {
    try {
        const queuePath = tasksClient.queuePath(PROJECT_ID, LOCATION, QUEUE_NAME);

        const payload = JSON.stringify({
            postId: postId,
            botUserId: botUserId
        });

        const task = {
            httpRequest: {
                httpMethod: 'POST',
                url: PROCESS_LIKE_URL,
                headers: {
                    'Content-Type': 'application/json',
                },
                body: Buffer.from(payload).toString('base64'),
            },
            scheduleTime: {
                seconds: Math.floor(Date.now() / 1000) + (delayMinutes * 60),
            },
        };

        const [response] = await tasksClient.createTask({ parent: queuePath, task });
        logger.info(`Created like task for post ${postId}, bot ${botUserId}, delay ${delayMinutes}m: ${response.name}`);
        return response.name;
    } catch (error) {
        logger.error(`Failed to schedule like task for post ${postId}:`, error);
        return null;
    }
}

/**
 * Analyze image using GPT-4 Vision
 */
async function analyzeImage(imageUrl, apiKey) {
    try {
        const openai = new OpenAI({ apiKey });

        const response = await openai.chat.completions.create({
            model: "gpt-4o-mini",
            messages: [
                {
                    role: "user",
                    content: [
                        {
                            type: "text",
                            text: "Describe this spiritual/meditation-related image briefly in 2-3 sentences. Focus on the mood, symbols, and spiritual significance."
                        },
                        {
                            type: "image_url",
                            image_url: { url: imageUrl }
                        }
                    ]
                }
            ],
            max_tokens: 150
        });

        return response.choices[0].message.content;
    } catch (error) {
        logger.warn(`Failed to analyze image: ${error.message}`);
        return null;
    }
}

/**
 * Analyze post content to extract topics and generate search queries for context.
 * Comments on ALL posts regardless of theme.
 * Returns { topics: string[], searchQueries: string[], language: string }
 */
async function analyzePostTheme(postText, imageDescription, apiKey) {
    try {
        const openai = new OpenAI({ apiKey });

        let contentToAnalyze = "";
        if (postText) {
            contentToAnalyze += `Post text: "${postText}"`;
        }
        if (imageDescription) {
            contentToAnalyze += `\n\nImage description: ${imageDescription}`;
        }

        if (!contentToAnalyze.trim()) {
            return { topics: [], searchQueries: [], language: "english" };
        }

        const response = await openai.chat.completions.create({
            model: "gpt-4o-mini",
            messages: [
                {
                    role: "system",
                    content: `You analyze posts from a spiritual/meditation app. Extract the key themes and generate search queries for relevant context.

Respond in JSON format:
{
  "topics": ["topic1", "topic2"],
  "searchQueries": ["search query 1", "search query 2"],
  "language": "hindi" or "english"
}

For topics: Identify the main themes (spiritual, philosophical, personal, emotional, cultural, etc.)
For searchQueries: Generate up to 2 queries to find relevant spiritual teachings, quotes, or wisdom that relate to the post's theme.
For language: Detect whether the post is primarily in Hindi (Devanagari script) or English.`
                },
                {
                    role: "user",
                    content: contentToAnalyze
                }
            ],
            max_tokens: 200,
            temperature: 0.3,
            response_format: { type: "json_object" }
        });

        const result = JSON.parse(response.choices[0].message.content);
        logger.info(`Post analysis: topics=${result.topics?.join(", ")}, language=${result.language}`);
        return result;
    } catch (error) {
        logger.warn(`Failed to analyze post theme: ${error.message}`);
        return { topics: [], searchQueries: [], language: "english" };
    }
}

/**
 * Perform web search using OpenAI's GPT web search (Responses API)
 */
async function gptWebSearch(query, apiKey) {
    try {
        const openai = new OpenAI({ apiKey });

        const response = await openai.responses.create({
            model: "gpt-4o-mini",
            tools: [{ type: "web_search_preview" }],
            input: query
        });

        // Extract search results from the response
        let searchContent = "";
        if (response.output) {
            for (const item of response.output) {
                if (item.type === "web_search_call" && item.status === "completed") {
                    // Web search was performed
                    logger.info(`GPT web search completed for: "${query}"`);
                } else if (item.type === "message" && item.content) {
                    // Extract text content from message
                    for (const content of item.content) {
                        if (content.type === "output_text") {
                            searchContent += content.text + "\n";
                        }
                    }
                }
            }
        }

        if (searchContent) {
            logger.info(`GPT web search for "${query}" returned content`);
            return searchContent.trim();
        }

        return null;
    } catch (error) {
        logger.warn(`GPT web search failed for "${query}": ${error.message}`);
        return null;
    }
}

/**
 * Perform up to 2 web searches using GPT and compile context
 */
async function gatherWebContext(searchQueries, apiKey) {
    if (!searchQueries || searchQueries.length === 0 || !apiKey) {
        return null;
    }

    const queriesToRun = searchQueries.slice(0, MAX_WEB_SEARCHES);
    const allResults = [];

    for (const query of queriesToRun) {
        const result = await gptWebSearch(query, apiKey);
        if (result) {
            allResults.push(`Search: "${query}"\n${result}`);
        }
    }

    if (allResults.length === 0) {
        return null;
    }

    // Compile context from search results
    return allResults.join("\n\n---\n\n");
}

/**
 * Get existing comments on a post
 */
async function getExistingComments(postId) {
    try {
        const commentsSnapshot = await db.collection('posts').doc(postId)
            .collection('Comments')
            .orderBy('createdAt', 'asc')
            .limit(10)
            .get();

        const comments = [];
        commentsSnapshot.forEach(doc => {
            const data = doc.data();
            comments.push({
                text: data.comment || data.text || '',
                userId: data.createdBy || data.userId || ''
            });
        });
        return comments;
    } catch (error) {
        logger.warn(`Failed to get existing comments: ${error.message}`);
        return [];
    }
}

/**
 * Generate a thoughtful comment using GPT-4o-mini.
 * Always comments in the same language as the post.
 * Sounds like a natural spiritual seeker and mentor.
 */
async function generateComment(postText, imageDescription, botPersona, existingComments, webContext, apiKey, postLanguage, creatorName, tagBotName) {
    try {
        const openai = new OpenAI({ apiKey });

        // Determine comment language: always match the post language
        const commentLang = postLanguage === "hindi" ? "Hindi (Devanagari script)" : "English";

        // Build context with text prioritized over image
        let contextInfo = "";

        // Primary context: Post text (highest priority)
        if (postText && postText.trim()) {
            contextInfo += `POST TEXT (this is your primary focus — respond to THIS):\n"${postText}"`;
        }

        // Secondary context: Web search results for relevant quotes/teachings
        if (webContext) {
            contextInfo += `\n\nRELEVANT CONTEXT FROM RESEARCH (use to enrich your comment):\n${webContext}`;
        }

        // Tertiary context: Image description (supplementary only)
        if (imageDescription) {
            contextInfo += `\n\nIMAGE CONTEXT (supplementary only, do not focus on this):\n${imageDescription}`;
        }

        let existingCommentsContext = "";
        if (existingComments && existingComments.length > 0) {
            existingCommentsContext = "\n\nExisting comments on this post:\n" +
                existingComments.map((c, i) => `${i + 1}. "${c.text}"`).join("\n") +
                "\n\nMake your comment unique and don't repeat what others have said.";
        }

        // Build tagging instructions
        let taggingInstruction = "";
        if (creatorName) {
            taggingInstruction += `\n- You MUST address the post creator as "@${creatorName} ji" in your comment`;
        }
        if (tagBotName) {
            taggingInstruction += `\n- You MUST also tag @${tagBotName} ji in your comment to bring them into the conversation`;
        }

        const systemPrompt = `You are ${botPersona.name}, a genuine spiritual seeker and mentor on Dhyanapp — a meditation and spirituality app.

Your persona: ${botPersona.persona}
Your conversational style: ${botPersona.conversational_style}
Your comment style: ${botPersona.comment_style}
Topics you focus on: ${botPersona.topics.join(", ")}
Teachers you follow: ${botPersona.follows.join(", ")}

You MUST write your comment in ${commentLang}. Match the language of the post.

Guidelines:
- Write a genuine, thoughtful comment (10-40 words) that sounds like a real spiritual seeker sharing wisdom
- Your PRIMARY context is always the post text — respond to what the person has written${taggingInstruction}
- Sound natural and warm, like a fellow practitioner on a shared path — not a bot or a commentator
- Share insights from your own spiritual journey and tradition
- Reference teachings, scriptures, or saints from your tradition when it flows naturally
- Be the kind of person others would want as a spiritual friend — thoughtful, humble, insightful
- Don't use hashtags or emojis
- Don't be preachy or lecture — share, don't teach down
- Don't be generic ("beautiful post!") — engage with the specific content`;

        const response = await openai.chat.completions.create({
            model: "gpt-4o-mini",
            messages: [
                { role: "system", content: systemPrompt },
                { role: "user", content: `Write a thoughtful comment on this post:\n\n${contextInfo}${existingCommentsContext}` }
            ],
            max_tokens: 200,
            temperature: 0.8
        });

        return response.choices[0].message.content.trim();
    } catch (error) {
        logger.error(`Failed to generate comment: ${error.message}`);
        return null;
    }
}

/**
 * Add a comment to a post
 * Note: commentCount is incremented by the existing handleCommentCreated Cloud Function
 */
async function addComment(postId, userId, text) {
    try {
        const createdAt = Date.now();
        const commentId = `${createdAt}${userId}`;

        const commentRef = db
            .collection('posts')
            .doc(postId)
            .collection('Comments')
            .doc(commentId);

        await commentRef.set({
            comment: text,
            commentId: commentId,
            commentLikesCount: 0,
            createdAt: createdAt,
            createdBy: userId,
            repliedTo: null
        });

        logger.info(`Comment added to post ${postId} by ${userId}`);
        return true;
    } catch (error) {
        logger.error(`Failed to add comment to post ${postId}:`, error);
        return false;
    }
}

/**
 * Shuffle array using Fisher-Yates algorithm
 */
function shuffleArray(array) {
    const shuffled = [...array];
    for (let i = shuffled.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
    }
    return shuffled;
}

/**
 * Main trigger: When a new post is created
 * - Add likes from all eligible bot accounts immediately
 * - Schedule 2 comment tasks with 1-minute and 16-minute delays
 */
exports.onPostCreated = onDocumentCreated({
    document: "posts/{postId}",
    region: LOCATION
}, async (event) => {
    const postData = event.data?.data();
    const postId = event.params.postId;

    if (!postData) {
        logger.warn(`No data for post ${postId}`);
        return;
    }

    // Skip if post is marked as deleted
    if (postData.isDeleted) {
        logger.info(`Post ${postId} is deleted, skipping engagement`);
        return;
    }

    const posterId = postData.createdBy || postData.userId;
    const creatorName = postData.creatorName || postData.userName || '';
    logger.info(`New post ${postId} by ${creatorName} (${posterId}), starting bot engagement...`);

    // Get bot accounts
    const botAccounts = await getBotAccounts();
    const botKeys = Object.keys(botAccounts);

    if (botKeys.length === 0) {
        logger.error("No bot accounts found");
        return;
    }

    // Filter out the poster if they are a bot
    const eligibleBotKeys = botKeys.filter(key => botAccounts[key].user_id !== posterId);

    if (eligibleBotKeys.length === 0) {
        logger.warn("No eligible bots to engage (poster might be the only bot)");
        return;
    }

    // Schedule likes from all eligible bots with ~5 minute delays between each
    const shuffledLikeBots = shuffleArray(eligibleBotKeys);
    logger.info(`Scheduling likes from ${shuffledLikeBots.length} bots with ${LIKE_DELAY_MINUTES}m intervals...`);

    for (let i = 0; i < shuffledLikeBots.length; i++) {
        const bot = botAccounts[shuffledLikeBots[i]];
        const delayMinutes = i * LIKE_DELAY_MINUTES; // 0, 5, 10, 15, 20, 25, 30, 35 minutes
        await scheduleLikeTask(postId, bot.user_id, delayMinutes);
    }

    logger.info(`Scheduled ${shuffledLikeBots.length} like tasks for post ${postId}`);

    // Select 2 random bots for commenting
    const shuffledBots = shuffleArray(eligibleBotKeys);
    const commentingBots = shuffledBots.slice(0, 2);

    logger.info(`Selected bots for commenting: ${commentingBots.join(", ")}`);

    // Schedule comment tasks
    // First comment: 5 minutes delay, tags the second bot
    // Second comment: 30 minutes delay, tags the first bot
    const delays = [5, 30];

    for (let i = 0; i < commentingBots.length; i++) {
        const botKey = commentingBots[i];
        const delay = delays[i];
        // Tag the other commenting bot
        const otherBotKey = commentingBots[1 - i];
        const otherBotName = botAccounts[otherBotKey]?.name || '';
        await scheduleCommentTask(postId, botKey, delay, creatorName, otherBotName);
    }

    logger.info(`Bot engagement setup complete for post ${postId}`);
});

/**
 * HTTP function: Process a scheduled comment task
 * Called by Cloud Tasks
 */
exports.processComment = onRequest({
    region: LOCATION,
    invoker: "public"  // Allow unauthenticated access for Cloud Tasks
}, async (req, res) => {
    // Validate request method
    if (req.method !== 'POST') {
        res.status(405).send('Method not allowed');
        return;
    }

    // Parse request body
    let payload;
    try {
        // Cloud Tasks sends body as base64 encoded
        if (req.body && typeof req.body === 'string') {
            payload = JSON.parse(Buffer.from(req.body, 'base64').toString());
        } else if (req.body && req.body.postId) {
            payload = req.body;
        } else {
            throw new Error('Invalid payload format');
        }
    } catch (error) {
        logger.error('Failed to parse request body:', error);
        res.status(400).send('Invalid request body');
        return;
    }

    const { postId, botKey, creatorName: payloadCreatorName, tagBotName } = payload;

    if (!postId || !botKey) {
        logger.error('Missing postId or botKey in payload');
        res.status(400).send('Missing required fields');
        return;
    }

    logger.info(`Processing comment task for post ${postId}, bot ${botKey}, creator ${payloadCreatorName || 'unknown'}, tag ${tagBotName || 'none'}`);

    try {
        // Get post data
        const postDoc = await db.collection('posts').doc(postId).get();
        if (!postDoc.exists) {
            logger.warn(`Post ${postId} not found`);
            res.status(404).send('Post not found');
            return;
        }

        const postData = postDoc.data();

        // Skip if post is deleted
        if (postData.isDeleted) {
            logger.info(`Post ${postId} is deleted, skipping comment`);
            res.status(200).send('Post deleted, skipping');
            return;
        }

        // Get bot account
        const botAccounts = await getBotAccounts();
        const bot = botAccounts[botKey];

        if (!bot) {
            logger.error(`Bot ${botKey} not found`);
            res.status(404).send('Bot not found');
            return;
        }

        // Get post content — primary field is 'content', fallback to 'text' and 'caption'
        const postText = postData.content || postData.text || postData.caption || '';
        const imageUrl = postData.imageURL || postData.imageUrl || null;
        const creatorName = payloadCreatorName || postData.creatorName || postData.userName || '';

        // Get API key from Firestore secrets
        const secrets = await getSecrets();
        const apiKey = secrets.OPENAI_API_KEY;

        if (!apiKey) {
            logger.error('OPENAI_API_KEY not found in config/secrets');
            res.status(500).send('API key not configured');
            return;
        }

        // Analyze image if present (do this first for theme analysis)
        let imageDescription = null;
        if (imageUrl) {
            imageDescription = await analyzeImage(imageUrl, apiKey);
        }

        // Analyze post theme and language for contextual commenting
        const themeAnalysis = await analyzePostTheme(postText, imageDescription, apiKey);
        const postLanguage = themeAnalysis.language || "english";

        logger.info(`Post ${postId} analysis - Topics: ${themeAnalysis.topics?.join(", ")}, Language: ${postLanguage}`);

        // Perform web searches for relevant context using GPT web search (up to 2 searches)
        let webContext = null;
        if (themeAnalysis.searchQueries && themeAnalysis.searchQueries.length > 0) {
            logger.info(`Performing GPT web searches: ${themeAnalysis.searchQueries.join(", ")}`);
            webContext = await gatherWebContext(themeAnalysis.searchQueries, apiKey);
            if (webContext) {
                logger.info(`Gathered web context: ${webContext.substring(0, 100)}...`);
            }
        }

        // Get existing comments for context
        const existingComments = await getExistingComments(postId);

        // Generate comment with text prioritized, web context, and matching post language
        const commentText = await generateComment(
            postText,
            imageDescription,
            bot,
            existingComments,
            webContext,
            apiKey,
            postLanguage,
            creatorName,
            tagBotName
        );

        if (!commentText) {
            logger.error(`Failed to generate comment for post ${postId}`);
            res.status(500).send('Failed to generate comment');
            return;
        }

        // Add the view (bot viewing the post)
        await addView(postId, bot.user_id);

        // Add the comment
        const success = await addComment(postId, bot.user_id, commentText);

        if (success) {
            logger.info(`Comment and view added successfully: "${commentText.substring(0, 50)}..."`);
            res.status(200).send('Comment and view added successfully');
        } else {
            res.status(500).send('Failed to add comment');
        }
    } catch (error) {
        logger.error(`Error processing comment task:`, error);
        res.status(500).send('Internal error');
    }
});

/**
 * HTTP function: Process a scheduled like task
 * Called by Cloud Tasks
 */
exports.processLike = onRequest({
    region: LOCATION,
    invoker: "public"  // Allow unauthenticated access for Cloud Tasks
}, async (req, res) => {
    // Validate request method
    if (req.method !== 'POST') {
        res.status(405).send('Method not allowed');
        return;
    }

    // Parse request body
    let payload;
    try {
        if (req.body && typeof req.body === 'string') {
            payload = JSON.parse(Buffer.from(req.body, 'base64').toString());
        } else if (req.body && req.body.postId) {
            payload = req.body;
        } else {
            throw new Error('Invalid payload format');
        }
    } catch (error) {
        logger.error('Failed to parse request body:', error);
        res.status(400).send('Invalid request body');
        return;
    }

    const { postId, botUserId } = payload;

    if (!postId || !botUserId) {
        logger.error('Missing postId or botUserId in payload');
        res.status(400).send('Missing required fields');
        return;
    }

    logger.info(`Processing like task for post ${postId}, bot ${botUserId}`);

    try {
        // Get post data to verify it still exists and isn't deleted
        const postDoc = await db.collection('posts').doc(postId).get();
        if (!postDoc.exists) {
            logger.warn(`Post ${postId} not found`);
            res.status(404).send('Post not found');
            return;
        }

        const postData = postDoc.data();

        // Skip if post is deleted
        if (postData.isDeleted || postData.deleted) {
            logger.info(`Post ${postId} is deleted, skipping like`);
            res.status(200).send('Post deleted, skipping');
            return;
        }

        // Add the view (bot viewing the post)
        await addView(postId, botUserId);

        // Add the like
        const success = await addLike(postId, botUserId);

        if (success) {
            logger.info(`Like and view added successfully to post ${postId} by ${botUserId}`);
            res.status(200).send('Like and view added successfully');
        } else {
            res.status(500).send('Failed to add like');
        }
    } catch (error) {
        logger.error(`Error processing like task:`, error);
        res.status(500).send('Internal error');
    }
});
