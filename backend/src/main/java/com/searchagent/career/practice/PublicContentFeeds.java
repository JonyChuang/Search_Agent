package com.searchagent.career.practice;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URI;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.locks.ReentrantLock;

import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilderFactory;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.w3c.dom.Element;

@Service
class PublicContentFeeds {
    private static final int MAX_FEED_SIZE = 512 * 1024;
    private static final Logger LOG = LoggerFactory.getLogger(PublicContentFeeds.class);

    private final PublicLearningContent content;
    private final List<URI> urls;
    private final ReentrantLock lock = new ReentrantLock();

    PublicContentFeeds(PublicLearningContent content, @Value("${career.content.feeds:}") String configured) {
        this.content = content;
        this.urls = Arrays.stream(configured.split(",")).map(String::strip).filter(value -> !value.isEmpty())
                .map(value -> {
                    String url = PublicLearningContent.webUrl(value);
                    if (url == null) throw new IllegalArgumentException("Invalid configured content feed");
                    return URI.create(url);
                }).distinct().toList();
    }

    int count() { return urls.size(); }

    @Scheduled(cron = "${career.content.refresh-cron:0 0 9 * * MON}", zone = "Asia/Shanghai")
    void scheduledRefresh() {
        if (!urls.isEmpty()) Thread.startVirtualThread(this::refresh);
    }

    Result refresh() {
        if (!lock.tryLock()) return new Result(0, 0, true);
        try {
            int succeeded = 0;
            int failed = 0;
            for (var source : urls) {
                try {
                    collect(source);
                    succeeded++;
                } catch (Exception error) {
                    LOG.warn("Public learning feed {} failed ({})", source.getHost(), error.getClass().getSimpleName());
                    failed++;
                }
            }
            return new Result(succeeded, failed, false);
        } finally {
            lock.unlock();
        }
    }

    private void collect(URI source) throws Exception {
        var connection = (HttpURLConnection) source.toURL().openConnection();
        connection.setInstanceFollowRedirects(false);
        connection.setConnectTimeout(4_000);
        connection.setReadTimeout(6_000);
        byte[] bytes;
        try {
            if (connection.getResponseCode() != 200) throw new IOException("Feed HTTP status " + connection.getResponseCode());
            try (var body = connection.getInputStream()) {
                bytes = body.readNBytes(MAX_FEED_SIZE + 1);
            }
        } finally {
            connection.disconnect();
        }
        if (bytes.length > MAX_FEED_SIZE) throw new IOException("Feed too large");
        collectEntries(source, bytes);
    }

    void collectEntries(URI source, byte[] bytes) throws Exception {
        var xml = DocumentBuilderFactory.newInstance();
        xml.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
        xml.setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, "");
        xml.setAttribute(XMLConstants.ACCESS_EXTERNAL_SCHEMA, "");
        xml.setNamespaceAware(true);
        var document = xml.newDocumentBuilder().parse(new ByteArrayInputStream(bytes));
        var entries = document.getElementsByTagNameNS("*", "item");
        boolean atom = entries.getLength() == 0;
        if (atom) entries = document.getElementsByTagNameNS("*", "entry");
        for (int index = 0; index < Math.min(20, entries.getLength()); index++) {
            var entry = (Element) entries.item(index);
            String link = atom ? atomLink(entry) : text(entry, "link");
            if (link.isBlank()) continue;
            try {
                String url = source.resolve(link).toASCIIString();
                String publication = text(entry, atom ? "published" : "pubDate");
                content.stageFeedNote(source.getHost(), url, text(entry, "title"), date(publication));
            } catch (IllegalArgumentException ignored) {
                // A bad entry does not block other candidates from the same source.
            }
        }
    }

    private static String atomLink(Element entry) {
        var links = entry.getElementsByTagNameNS("*", "link");
        for (int i = 0; i < links.getLength(); i++) {
            var link = (Element) links.item(i);
            String relation = link.getAttribute("rel");
            if (relation.isEmpty() || "alternate".equals(relation)) return link.getAttribute("href");
        }
        return "";
    }

    private static String text(Element entry, String name) {
        var tags = entry.getElementsByTagNameNS("*", name);
        return tags.getLength() == 0 ? "" : tags.item(0).getTextContent().strip();
    }

    private static LocalDate date(String value) {
        try {
            return OffsetDateTime.parse(value).toLocalDate();
        } catch (DateTimeParseException ignored) {
            try {
                return ZonedDateTime.parse(value, DateTimeFormatter.RFC_1123_DATE_TIME).toLocalDate();
            } catch (DateTimeParseException unknown) {
                try { return LocalDate.parse(value); }
                catch (DateTimeParseException absent) { return null; }
            }
        }
    }

    record Result(int succeeded, int failed, boolean busy) {}
}

