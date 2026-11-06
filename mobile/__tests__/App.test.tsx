/**
 * @format
 */

import React from 'react';
import ReactTestRenderer from 'react-test-renderer';
import App from '../App';

jest.mock('react-native-safe-area-context', () => require('react-native-safe-area-context/jest/mock').default);
jest.mock('../src/native', () => {
  const state = {status: 'anonymous', server: '', token: '', user: null, error: ''};
  return {
    session: {snapshot: () => state, subscribe: () => () => {}, restore: jest.fn().mockResolvedValue(undefined)},
    clearPhotos: jest.fn().mockResolvedValue(undefined),
  };
});

test('renders correctly', async () => {
  await ReactTestRenderer.act(() => {
    ReactTestRenderer.create(<App />);
  });
});
