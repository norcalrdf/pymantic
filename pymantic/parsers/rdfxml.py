import re
from threading import local
from urllib.parse import (
    urljoin,
)

from lxml import etree

from pymantic.primitives import (
    BlankNode,
    NamedNode,
)


scheme_re = re.compile(r'[a-zA-Z](?:[a-zA-Z0-9]|\+|-|\.)*')


class RDFXMLParser(object):
    RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'

    def __init__(self):
        self.namespaces = {
            'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
        }
        self._call_state = local()

    def clark(self, prefix, tag):
        return '{%s}%s' % (self.namespaces[prefix], tag)

    def parse(self, f, sink=None):
        self._call_state.bnodes = {}
        tree = etree.parse(f)
        if tree.getroot() != self.clark('rdf', 'RDF'):
            raise ValueError('Invalid XML document.')
        for element in tree.getroot():
            self._handle_resource(element, sink)

    def _handle_resource(self, element, sink):
        from pymantic.primitives import NamedNode, Triple
        subject = self._determine_subject(element)
        if element.tag != self.clark('rdf', 'Description'):
            resource_class = self._resolve_tag(element)
            sink.add(Triple(subject, NamedNode(self.RDF_TYPE), resource_class))
        for property_element in element:
            if property_element.tag == self.clark('rdf', 'li'):
                pass
            else:
                predicate = self._resolve_tag(property_element)
            if self.clark('rdf', 'resource') in property_element.attrib:
                object_ = self._resolve_uri(
                    property_element, property_element.attrib[self.clark(
                        'rdf', 'resource')])
                sink.add(
                    Triple(subject, NamedNode(predicate), NamedNode(object_)))
        return subject

    def _resolve_tag(self, element):
        if element.tag[0] == '{':
            tag_bits = element[1:].partition('}')
            return NamedNode(tag_bits[0] + tag_bits[2])
        else:
            return NamedNode(urljoin(element.base, element.tag))

    def _determine_subject(self, element):
        if self.clark('rdf', 'about') not in element.attrib and\
           self.clark('rdf', 'nodeID') not in element.attrib and\
           self.clark('rdf', 'ID') not in element.attrib:
            return BlankNode()
        elif self.clark('rdf', 'nodeID') in element.attrib:
            node_id = element.attrib[self.clark('rdf', 'nodeID')]
            if node_id not in self._call_state.bnodes:
                self._call_state.bnodes[node_id] = BlankNode()
            return self._call_state.bnodes[node_id]
        elif self.clark('rdf', 'ID') in element.attrib:
            if not element.base:
                raise ValueError('No XML base for %r', element)
            return NamedNode(element.base + '#' +
                             element.attrib[self.clark('rdf', 'ID')])
        elif self.clark('rdf', 'about') in element.attrib:
            return self._resolve_uri(element, element.attrib[
                self.clark('rdf', 'resource')])

    def _resolve_uri(self, element, uri):
        if not scheme_re.match(uri):
            return NamedNode(urljoin(element.base, uri))
        else:
            return NamedNode(uri)
