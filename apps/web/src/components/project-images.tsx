"use client";

import { useCallback, useMemo, useState } from "react";

import { imageCredit, usableImages, type ProjectDetail, type ProjectImage } from "./trackstar-final-ui";
import styles from "./project-images.module.css";

// These files are hotlinked from city web servers that go down, rate-limit and
// 403 without warning. A failed load must leave no trace: no broken-image glyph,
// no reserved gap, no half-rendered credit. Everything below is built so that
// dropping an image is the cheap path and showing a broken one is impossible.

function imageAlt(image: ProjectImage, projectName: string) {
  const caption = image.caption?.trim();
  if (caption) return caption;
  const credit = imageCredit(image);
  return credit ? `${projectName}, photograph published by ${credit}` : `${projectName} photograph`;
}

function linkTarget(image: ProjectImage) {
  const source = image.source_url?.trim();
  // Falling back to the file itself still lands the reader on the publisher's
  // own server, so the credit line is never a dead end.
  return source && /^https?:\/\//i.test(source) ? source : image.asset_url;
}

export function useProjectImages(detail: ProjectDetail | null) {
  const [failed, setFailed] = useState<Record<string, true>>({});
  const markFailed = useCallback((url: string) => {
    setFailed((current) => (current[url] ? current : { ...current, [url]: true }));
  }, []);

  const available = useMemo(
    () => usableImages(detail).filter((image) => !failed[image.asset_url]),
    [detail, failed],
  );

  return { hero: available[0] ?? null, strip: available.slice(1), markFailed };
}

function Credit({ image }: { image: ProjectImage }) {
  const credit = imageCredit(image);
  const caption = image.caption?.trim();
  return (
    <span className={styles.credit}>
      {caption ? <span className={styles.caption}>{caption}</span> : null}
      <span className={styles.source}>
        {image.is_official ? <span className={styles.official}>Official</span> : null}
        <span className={styles.publisher}>{credit}</span>
        <span aria-hidden="true" className={styles.arrow}>↗</span>
      </span>
    </span>
  );
}

export function ProjectHeroImage({ image, projectName, onFailed }: {
  image: ProjectImage | null;
  projectName: string;
  onFailed: (url: string) => void;
}) {
  if (!image) return null;
  return (
    <figure className={styles.hero}>
      <a className={styles.heroLink} href={linkTarget(image)} rel="noreferrer" target="_blank">
        <img
          alt={imageAlt(image, projectName)}
          className={styles.heroImage}
          decoding="async"
          height={900}
          loading="lazy"
          onError={() => onFailed(image.asset_url)}
          referrerPolicy="no-referrer"
          src={image.asset_url}
          width={1600}
        />
        <figcaption className={styles.heroCaption}><Credit image={image} /></figcaption>
      </a>
    </figure>
  );
}

export function ProjectImageStrip({ images, projectName, onFailed }: {
  images: ProjectImage[];
  projectName: string;
  onFailed: (url: string) => void;
}) {
  if (!images.length) return null;
  return (
    <section className={styles.stripBlock}>
      <p className={styles.stripLabel}>More photos</p>
      <ul aria-label={`More photographs of ${projectName}`} className={styles.strip}>
        {images.map((image) => (
          <li className={styles.stripItem} key={image.asset_url}>
            <a className={styles.stripLink} href={linkTarget(image)} rel="noreferrer" target="_blank">
              <img
                alt={imageAlt(image, projectName)}
                className={styles.stripImage}
                decoding="async"
                height={900}
                loading="lazy"
                onError={() => onFailed(image.asset_url)}
                referrerPolicy="no-referrer"
                src={image.asset_url}
                width={1600}
              />
              <Credit image={image} />
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
