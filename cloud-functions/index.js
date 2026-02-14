/**
 * DhyanApp Bot Engagement Cloud Functions
 *
 * This module handles automatic engagement (likes and comments) on posts:
 * - onPostCreated: Triggered when a new post is created
 * - processComment: HTTP function to generate and post AI comments
 * - processLike: HTTP function to add likes from bot accounts
 */

const admin = require("firebase-admin");

// Initialize Firebase Admin
admin.initializeApp();

// Import bot engagement functions
const botEngagement = require("./botEngagement");

// Export bot engagement functions
exports.onPostCreated = botEngagement.onPostCreated;
exports.processComment = botEngagement.processComment;
exports.processLike = botEngagement.processLike;
