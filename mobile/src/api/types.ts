import type {components} from './schema';

export type User = components['schemas']['UserView'];
export type LoginResult = components['schemas']['LoginResult'];
export type Family = components['schemas']['FamilyView'];
export type Document = components['schemas']['DocumentView'];
export type Job = components['schemas']['ProcessingJobView'];
export type Index = components['schemas']['DocumentIndexView'];
export type Visibility = components['schemas']['Visibility'];

export interface LocalFile {
  uri: string;
  name: string;
  size: number;
  type: string;
  key: string;
}
