Imports System
Imports System.Collections.Generic
Imports System.Net.Http

Namespace GraphifyDemo

    Public Interface IProcessor
        Function Process(items As List(Of String)) As List(Of String)
    End Interface

    Public Class DataProcessor
        Inherits BaseProcessor
        Implements IProcessor

        Private ReadOnly _client As HttpClient

        Public Sub New()
            _client = New HttpClient()
        End Sub

        Public Function Process(items As List(Of String)) As List(Of String)
            Return Validate(items)
        End Function

        Private Function Validate(items As List(Of String)) As List(Of String)
            Dim result As New List(Of String)
            For Each item In items
                If Not String.IsNullOrEmpty(item) Then
                    result.Add(item.Trim())
                End If
            Next
            Return result
        End Function

    End Class

    Public Module AppHelper

        Public Sub Run(processor As IProcessor)
            Dim data As New List(Of String)
            data.Add("hello")
            processor.Process(data)
        End Sub

    End Module

    Public Structure Point
        Implements IComparable

        Public X As Double
        Public Y As Double

        Public Function CompareTo(obj As Object) As Integer
            Return 0
        End Function

    End Structure

End Namespace
