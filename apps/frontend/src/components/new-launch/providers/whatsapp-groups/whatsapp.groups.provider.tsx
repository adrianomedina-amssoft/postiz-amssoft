'use client';
import { PostComment, withProvider } from '../high.order.provider';
export default withProvider({ postComment: PostComment.COMMENT, comments: false, minimumCharacters: [], SettingsComponent: null, dto: undefined, maximumCharacters: 1024 });
